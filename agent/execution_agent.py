"""Execution BaseAgent — deterministic order placement, credentials firewall.

Reads state["pending_order"] (PendingOrder schema) written by the coordinator,
routes to the correct broker by asset_class, places the order, and always writes
a terminal status back to state["order_result"] regardless of outcome.

Asset class routing:
    etf / crypto  → Alpaca paper trading (ALPACA_API_KEY / ALPACA_API_SECRET env vars)
    forex         → OANDA practice account (stub — implemented in PR 2)

Recovery guarantee: every path through _run_async_impl writes state["order_result"]
before yielding the final Event, so the coordinator can always read the outcome.
"""
from __future__ import annotations

import logging
import os
from typing import AsyncGenerator

from google.adk.agents import BaseAgent  # type: ignore[import]
from google.adk.agents.invocation_context import InvocationContext  # type: ignore[import]
from google.adk.events import Event, EventActions  # type: ignore[import]

from tools.schemas import PendingOrder, OrderResultOutput

logger = logging.getLogger("agent.execution")


class ExecutionAgent(BaseAgent):
    """Thin execution layer — no LLM, just deterministic order routing."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        raw = state.get("pending_order")

        if not raw:
            state["order_result"] = OrderResultOutput(
                order_id="",
                status="failed",
                symbol="",
                qty=0.0,
                side="",
                type="",
            ).model_dump()
            state["order_result"]["error"] = "pending_order missing from state"
            yield Event(author=self.name, actions=EventActions(escalate=True))
            return

        try:
            order = PendingOrder(**raw) if isinstance(raw, dict) else raw
        except Exception as exc:
            state["order_result"] = _error_result("", f"invalid pending_order: {exc}")
            yield Event(author=self.name, actions=EventActions(escalate=True))
            return

        logger.info(
            "execution_agent: %s %s %s asset_class=%s",
            order.side, order.symbol, order.order_type, order.asset_class,
        )

        if order.asset_class in ("etf", "crypto"):
            result = await _execute_alpaca(order)
        elif order.asset_class == "forex":
            result = await _execute_forex_stub(order)
        else:
            result = _error_result(order.symbol, f"unknown asset_class: {order.asset_class}")

        state["order_result"] = result
        yield Event(author=self.name, actions=EventActions(escalate=True))


# ── Alpaca execution ──────────────────────────────────────────────────────────

async def _execute_alpaca(order: PendingOrder) -> dict:
    from infra.rate_limiter import acquire_alpaca_trading

    api_key = os.environ.get("ALPACA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_API_SECRET", "")
    if not api_key or not api_secret:
        return _error_result(order.symbol, "ALPACA_API_KEY / ALPACA_API_SECRET not set")

    try:
        from alpaca.trading.client import TradingClient  # type: ignore[import]
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest  # type: ignore[import]
        from alpaca.trading.enums import OrderSide, TimeInForce  # type: ignore[import]

        await acquire_alpaca_trading()
        client = TradingClient(api_key=api_key, secret_key=api_secret, paper=True)

        side = OrderSide.BUY if order.side.lower() == "buy" else OrderSide.SELL

        # Determine quantity
        qty = order.qty
        if qty is None or qty <= 0:
            account = client.get_account()
            buying_power = float(account.buying_power)
            quote_price = _get_last_price(order.symbol, client)
            if quote_price and quote_price > 0:
                raw_qty = (buying_power * order.buying_power_pct) / quote_price
                qty = max(1.0, round(raw_qty, 0))
            else:
                return _error_result(order.symbol, "could not determine price for sizing")

        if order.order_type == "limit" and order.limit_price:
            req = LimitOrderRequest(
                symbol=order.symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY,
                limit_price=order.limit_price,
            )
            placed = client.submit_order(req)
        else:
            req = MarketOrderRequest(
                symbol=order.symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY,
            )
            placed = client.submit_order(req)

        return OrderResultOutput(
            order_id=str(placed.id),
            status=str(placed.status),
            symbol=str(placed.symbol),
            qty=float(placed.qty or qty),
            side=order.side,
            type=order.order_type,
            limit_price=float(placed.limit_price) if placed.limit_price else None,
            submitted_at=placed.submitted_at.isoformat() if placed.submitted_at else None,
        ).model_dump()

    except Exception as exc:
        logger.error("execution_agent alpaca error: %s", exc)
        return _error_result(order.symbol, f"broker_error: {exc}")


def _get_last_price(symbol: str, client: object) -> float | None:
    try:
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore[import]
        from alpaca.data.requests import StockLatestQuoteRequest  # type: ignore[import]
        data_client = StockHistoricalDataClient()
        resp = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
        quote = resp.get(symbol)
        if quote:
            return float((quote.ask_price + quote.bid_price) / 2)
    except Exception:
        pass
    return None


# ── Forex stub (PR 2) ─────────────────────────────────────────────────────────

async def _execute_forex_stub(order: PendingOrder) -> dict:
    logger.warning("execution_agent: forex execution not yet implemented (PR 2)")
    return _error_result(order.symbol, "forex_not_implemented: coming in PR 2")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _error_result(symbol: str, error: str) -> dict:
    result = OrderResultOutput(
        order_id="",
        status="failed",
        symbol=symbol,
        qty=0.0,
        side="",
        type="",
    ).model_dump()
    result["error"] = error
    return result


def create_execution_agent(model: str = "gemini-2.5-flash") -> ExecutionAgent:
    """Factory: returns a fresh ExecutionAgent instance.

    The model param is accepted for API consistency but unused — ExecutionAgent
    is a BaseAgent with no LLM. Credentials must be injected as env vars before
    the agent is invoked.
    """
    return ExecutionAgent(
        name="execution_agent",
        description=(
            "Deterministic order placement layer. Reads state['pending_order'], "
            "routes to Alpaca (etf/crypto) or OANDA (forex), writes state['order_result']."
        ),
        sub_agents=[],
    )
