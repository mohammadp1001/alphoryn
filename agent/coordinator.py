"""
Coordinator agent — top-level orchestrator for the trading decision cycle.

Architecture:
  Coordinator (LlmAgent — Gemini 2.5 Flash)
    ├── ALL_COORDINATOR_TOOLS  (analysis/workflow/memory/coordinator/strategy/file)
    ├── AgentTool(debate_optimist)  — parallel risk debate (optimist)
    ├── AgentTool(debate_pessimist) — parallel risk debate (pessimist)
    ├── AgentTool(research_agent)   — news and sentiment research
    ├── AgentTool(execution_agent)  — BaseAgent: deterministic order routing
    └── MCPToolset(Alpaca MCP)      — portfolio, account, and market clock (optional)

Execution tools are NEVER on the coordinator; it writes state["pending_order"] and
delegates to the execution AgentTool. Market data comes from the Alpaca MCP server
when ALPACA_MCP_URL is set; otherwise the coordinator falls back to its direct tools.

Factory pattern prevents "agent already has a parent" ADK errors across sessions.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from google.adk.agents import Agent  # type: ignore[import]
from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]
from google.adk.tools import AgentTool  # type: ignore[import]

from agent.debate_agents import create_debate_optimist, create_debate_pessimist
from agent.execution_agent import create_execution_agent
from agent.preflight import run_preflight
from agent.prompts import COORDINATOR_INSTRUCTION
from agent.research_agent import create_research_agent
from infra.observability import log_action
from models.session import PlanState, SessionParams
from tools.registry import ALL_COORDINATOR_TOOLS

_DEFAULT_COORDINATOR_MODEL = "gemini-2.5-flash"


def _resolve_model(model_str: str | None) -> object:
    """Return a bare string for Gemini models, LiteLlm wrapper for OpenRouter."""
    if not model_str:
        return _DEFAULT_COORDINATOR_MODEL
    if model_str.startswith("openrouter/"):
        from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

        return LiteLlm(model=model_str)
    return model_str


def _alpaca_mcp_tools() -> list:
    """Return MCPToolset for the Alpaca MCP server if ALPACA_MCP_URL is configured."""
    mcp_url = os.environ.get("ALPACA_MCP_URL", "")
    if not mcp_url:
        return []
    try:
        from google.adk.tools.mcp_tool.mcp_toolset import (  # type: ignore[import]
            MCPToolset,
            SseServerParams,
        )

        return [MCPToolset(connection_params=SseServerParams(url=mcp_url))]
    except ImportError:
        log_action(
            "coordinator",
            "mcp_init",
            logging.WARNING,
            status="disabled",
            reason="MCPToolset_not_available",
        )
        return []


def create_coordinator(
    params: SessionParams,
    plan_state: PlanState,
    model: object = None,
) -> Agent:
    """Factory: returns a fully wired coordinator agent for one session.

    Args:
        params: Session configuration (strategy, mode, limits, etc.).
        plan_state: Initial PlanState for this session.
        model: Model for the coordinator. None → use params.coordinator_model or default
               Gemini 2.5 Flash. Pass a bare string for Gemini, or LiteLlm() for others.
    """
    if model is None:
        model = _resolve_model(params.coordinator_model)
    _placeholder_cal = "Calibration data will be loaded at the start of each cycle."

    debate_optimist_tool = AgentTool(agent=create_debate_optimist(_placeholder_cal))
    debate_pessimist_tool = AgentTool(agent=create_debate_pessimist(_placeholder_cal))
    research_tool = AgentTool(agent=create_research_agent(plan_state.session_id, symbol=""))
    execution_tool = AgentTool(agent=create_execution_agent())

    from config import DEFAULT_ETF_UNIVERSE, ETF_UNIVERSES, UNIVERSE_EXCHANGE_TZ

    universe_symbols = ETF_UNIVERSES.get(params.universe, DEFAULT_ETF_UNIVERSE)
    symbols_str = ", ".join(universe_symbols)
    exchange_tz = UNIVERSE_EXCHANGE_TZ.get(params.universe, "America/New_York")
    session_expires_at = (plan_state.started_at + params.duration).isoformat() + "Z"

    from config import MAX_STRATEGY_CYCLES

    instruction = COORDINATOR_INSTRUCTION.format(
        session_id=plan_state.session_id,
        mode=params.mode.value,
        loss_limit_eur=params.loss_limit_eur,
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
            debate_optimist_tool,
            debate_pessimist_tool,
            research_tool,
            execution_tool,
            *ALL_COORDINATOR_TOOLS,
            *_alpaca_mcp_tools(),
        ],
        before_agent_callback=before_cb,
        description=(
            "Top-level coordinator. Runs analysis workflows, debates risk, "
            "and executes approved trades."
        ),
    )


def _make_before_callback(params: SessionParams, plan_state: PlanState):
    """Return a before_agent_callback that runs pre-flight checks then pre-fetches portfolio.

    Pre-flight sequence (deterministic — no LLM involved):
      0. Session expiry + market hours gate
      1. Loss limit check
      2. Resolve unresolved trades (session-start only)

    Returns a Content object to abort the coordinator turn when any check fails;
    returns None to let the coordinator proceed normally.
    """
    from config import UNIVERSE_EXCHANGE_TZ

    exchange_tz = UNIVERSE_EXCHANGE_TZ.get(params.universe, "America/New_York")
    session_expires_at = plan_state.started_at + params.duration

    async def before_callback(callback_context: CallbackContext):  # -> Optional[Content]
        from infra.rate_limiter import acquire_gemini

        await acquire_gemini()

        state = callback_context.state

        # ── One-time session initialisation ───────────────────────────────────
        is_first_run = "session_initialised" not in state
        if is_first_run:
            from db.schema import init_db

            init_db()
            state["session_initialised"] = True
            state["cycle_count"] = 0
            state["active_strategy"] = ""
            state["strategies_tried_this_cycle"] = []
            log_action("coordinator", "session_init", session_id=plan_state.session_id)

        # ── Pre-fetch portfolio and account snapshots ─────────────────────────
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
                log_action(
                    "coordinator",
                    "portfolio_fetch",
                    positions=len(positions),
                    buying_power=f"{float(account.buying_power):.2f}",
                )
            except Exception as exc:
                log_action(
                    "coordinator",
                    "portfolio_fetch",
                    logging.WARNING,
                    status="failed",
                    error=str(exc),
                )
                state.setdefault("account_snapshot", {})
                state.setdefault("portfolio_snapshot", {"positions": [], "position_count": 0})
        else:
            log_action(
                "coordinator",
                "portfolio_fetch",
                logging.DEBUG,
                status="skipped",
                reason="no_credentials",
            )
            state.setdefault("account_snapshot", {})
            state.setdefault("portfolio_snapshot", {"positions": [], "position_count": 0})

        # ── Deterministic pre-flight checks ───────────────────────────────────
        portfolio = state.get("portfolio_snapshot", {})
        unrealised_pnl = sum(
            p.get("unrealised_pnl", 0.0) for p in portfolio.get("positions", [])
        )

        result = await run_preflight(
            session_id=plan_state.session_id,
            session_expires_at=session_expires_at,
            exchange_tz=exchange_tz,
            allow_closed_market=params.allow_closed_market,
            loss_limit_eur=params.loss_limit_eur,
            session_realised_pnl_eur=state.get("session_realised_pnl_eur", 0.0),
            unrealised_pnl_eur=unrealised_pnl,
            resolve_trades=is_first_run,
        )

        for msg in result.messages:
            log_action("coordinator", "preflight", message=msg)

        if not result.ok:
            state["session_abort"] = {
                "stage": result.abort_stage,
                "reason": result.abort_reason,
            }
            log_action(
                "coordinator",
                "preflight_abort",
                logging.WARNING,
                stage=result.abort_stage,
                reason=result.abort_reason,
                session_id=plan_state.session_id,
            )
            from google.genai.types import Content, Part  # type: ignore[import]

            return Content(role="model", parts=[Part(text=result.report)])

        return None

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
