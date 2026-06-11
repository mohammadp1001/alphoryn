"""
Coordinator agent — top-level orchestrator for the trading decision cycle.

Architecture (flattened):
  Coordinator (LlmAgent — Gemini 2.5 Flash)
    ├── ALL_COORDINATOR_TOOLS  (market/analysis/research/memory/coordinator/strategy)
    ├── AgentTool(risk_debate) — SequentialAgent: optimist → pessimist
    └── AgentTool(execution_agent) — BaseAgent: deterministic order routing

The coordinator directly calls all data/analysis tools and accumulates results in
session.state before invoking the risk debate. Execution tools are NEVER on the
coordinator; it writes state["pending_order"] and delegates to the execution AgentTool.

Factory pattern prevents "agent already has a parent" ADK errors across sessions.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from google.adk.agents import Agent  # type: ignore[import]
from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]
from google.adk.tools import AgentTool  # type: ignore[import]

from agent.execution_agent import create_execution_agent
from agent.prompts import COORDINATOR_INSTRUCTION
from agent.risk_agents import create_risk_debate
from models.session import PlanState, SessionParams
from tools.registry import ALL_COORDINATOR_TOOLS

logger = logging.getLogger("agent.coordinator")


def create_coordinator(
    params: SessionParams,
    plan_state: PlanState,
    model: str = "gemini-2.5-flash",
) -> Agent:
    """Factory: returns a fully wired coordinator agent for one session.

    Args:
        params: Session configuration (strategy, mode, limits, etc.).
        plan_state: Initial PlanState for this session.
        model: Gemini model ID for the coordinator. Default: gemini-2.5-flash.
    """
    _placeholder_cal = "Calibration data will be loaded at the start of each cycle."

    risk_debate_tool = AgentTool(
        agent=create_risk_debate(_placeholder_cal, _placeholder_cal)
    )
    execution_tool = AgentTool(agent=create_execution_agent())

    from config import DEFAULT_ETF_UNIVERSE, ETF_UNIVERSES, UNIVERSE_EXCHANGE_TZ
    universe_symbols = ETF_UNIVERSES.get(params.universe, DEFAULT_ETF_UNIVERSE)
    symbols_str = ", ".join(universe_symbols)
    exchange_tz = UNIVERSE_EXCHANGE_TZ.get(params.universe, "America/New_York")
    session_expires_at = (plan_state.started_at + params.duration).isoformat()

    from config import MAX_STRATEGY_CYCLES
    instruction = COORDINATOR_INSTRUCTION.format(
        session_id=plan_state.session_id,
        mode=params.mode.value,
        loss_limit_eur=params.loss_limit_eur,
        shortlist_n=params.shortlist_n,
        hitl_timeout_seconds=params.hitl_timeout_seconds,
        hitl_timeout_action=params.hitl_timeout_action,
        universe=params.universe,
        symbols=symbols_str,
        exchange_tz=exchange_tz,
        timeframe=params.timeframe.value,
        session_expires_at=session_expires_at,
        max_strategy_cycles=MAX_STRATEGY_CYCLES,
        allow_closed_market=str(params.allow_closed_market).lower(),
    )

    before_cb = _make_before_callback(params, plan_state)

    return Agent(
        name="coordinator",
        model=model,
        instruction=instruction,
        tools=[
            risk_debate_tool,
            execution_tool,
            *ALL_COORDINATOR_TOOLS,
        ],
        before_agent_callback=before_cb,
        description=(
            "Top-level coordinator. Researches markets, screens candidates, "
            "debates risk, and executes approved trades."
        ),
    )


def _make_before_callback(params: SessionParams, plan_state: PlanState):
    """Return a before_agent_callback that pre-fetches portfolio/account into state."""

    async def before_callback(callback_context: CallbackContext) -> None:
        from infra.rate_limiter import acquire_gemini
        await acquire_gemini()

        state = callback_context.state

        # One-time session initialisation
        if "session_initialised" not in state:
            from db.schema import init_db
            init_db()
            state["session_initialised"] = True
            state["cycle_count"] = 0
            state["active_strategy"] = ""

        # Pre-fetch portfolio and account snapshots before each coordinator turn.
        # Credentials must be present in env; if not, snapshots are skipped (paper mode).
        api_key = os.environ.get("ALPACA_API_KEY", "")
        api_secret = os.environ.get("ALPACA_API_SECRET", "")
        if api_key and api_secret:
            try:
                from alpaca.trading.client import TradingClient  # type: ignore[import]

                from infra.rate_limiter import acquire_alpaca_trading
                await acquire_alpaca_trading()
                client = TradingClient(api_key=api_key, secret_key=api_secret, paper=True)

                account = client.get_account()
                state["account_snapshot"] = {
                    "buying_power": float(account.buying_power),
                    "cash": float(account.cash),
                    "portfolio_value": float(account.portfolio_value),
                    "daytrade_count": int(account.daytrade_count),
                    "pattern_day_trader": bool(account.pattern_day_trader),
                    "status": str(account.status),
                }

                positions = client.get_all_positions()
                state["portfolio_snapshot"] = {
                    "positions": [
                        {
                            "symbol": str(p.symbol),
                            "qty": float(p.qty),
                            "side": str(p.side),
                            "avg_entry_price": float(p.avg_entry_price or 0),
                            "market_value": float(p.market_value or 0),
                            "unrealised_pnl": float(p.unrealized_pl or 0),
                        }
                        for p in positions
                    ],
                    "position_count": len(positions),
                }
                logger.debug(
                    "before_callback: portfolio fetched — %d positions, buying_power=%.2f",
                    len(positions),
                    float(account.buying_power),
                )
            except Exception as exc:
                logger.warning("before_callback: portfolio fetch failed — %s", exc)
                state.setdefault("account_snapshot", {})
                state.setdefault("portfolio_snapshot", {"positions": [], "position_count": 0})
        else:
            logger.debug("before_callback: no Alpaca credentials — skipping portfolio prefetch")
            state.setdefault("account_snapshot", {})
            state.setdefault("portfolio_snapshot", {"positions": [], "position_count": 0})

    return before_callback


def build_app(params: SessionParams) -> Any:
    """Build an ADK Runner App for one trading session.

    Returns (runner, session_id, plan_state, session_service).
    Caller must await session_service.create_session(...) before run_async().
    """
    import uuid

    from google.adk.runners import Runner  # type: ignore[import]
    from google.adk.sessions import InMemorySessionService  # type: ignore[import]

    session_id = str(uuid.uuid4())
    plan_state = PlanState(
        session_id=session_id,
        params=params,
    )

    coordinator = create_coordinator(params, plan_state)
    session_service = InMemorySessionService()

    runner = Runner(
        agent=coordinator,
        app_name="alphoryn",
        session_service=session_service,
    )
    return runner, session_id, plan_state, session_service
