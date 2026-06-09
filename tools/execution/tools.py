"""execution.* tools — 8 tools, execution agent scope.

SECURITY: These tools read Alpaca credentials from environment variables only.
Credentials must be injected by coordinator harness at spawn time and must never
be logged, stored on PlanState, or forwarded to any other agent.

NOTE: @with_retry is intentionally NOT applied to place_* tools per retry policy.
Order submission is not idempotent.
"""
from __future__ import annotations

import os

from infra.observability import api_call_span
from infra.rate_limiter import acquire_alpaca_trading
from infra.retry import with_retry


def _trading_client():
    from alpaca.trading.client import TradingClient  # type: ignore[import]

    return TradingClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_API_SECRET"],
        paper=True,
    )


async def get_portfolio() -> dict:
    """Load current portfolio positions and account status from Alpaca.

    Returns:
        dict with 'positions' (list), 'cash_usd', 'portfolio_value', 'buying_power', 'is_paper'.
    """
    await acquire_alpaca_trading()
    async with api_call_span("alpaca_trading", "get_portfolio"):
        client = _trading_client()
        account = client.get_account()
        positions = client.get_all_positions()

    pos_list = [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": str(p.side).lower(),
            "avg_entry_price": float(p.avg_entry_price),
            "market_value": float(p.market_value),
            "unrealised_pnl": float(p.unrealized_pl),
            "unrealised_pnl_pct": float(p.unrealized_plpc) * 100,
        }
        for p in positions
    ]
    return {
        "positions": pos_list,
        "cash_usd": float(account.cash),
        "portfolio_value": float(account.portfolio_value),
        "buying_power": float(account.buying_power),
        "is_paper": True,
    }


@with_retry
async def get_position(symbol: str) -> dict:
    """Get current position for a specific symbol.

    Args:
        symbol: Ticker symbol.

    Returns:
        dict with position details or 'has_position': false if not held.
    """
    await acquire_alpaca_trading()
    async with api_call_span("alpaca_trading", "get_position", symbol=symbol):
        client = _trading_client()
        try:
            p = client.get_open_position(symbol)
            return {
                "symbol": p.symbol,
                "has_position": True,
                "qty": float(p.qty),
                "side": str(p.side).lower(),
                "avg_entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "unrealised_pnl": float(p.unrealized_pl),
                "unrealised_pnl_pct": float(p.unrealized_plpc) * 100,
            }
        except Exception:
            return {"symbol": symbol, "has_position": False}


async def place_market_order(symbol: str, qty: float, side: str) -> dict:
    """Place a market order. NOT retried on failure — orders are not idempotent.

    Args:
        symbol: Ticker symbol.
        qty: Number of shares (fractional supported).
        side: 'buy' or 'sell'.

    Returns:
        dict with 'order_id', 'status', 'symbol', 'qty', 'side', 'type', 'submitted_at'.
    """
    from alpaca.trading.requests import MarketOrderRequest  # type: ignore[import]
    from alpaca.trading.enums import OrderSide, TimeInForce  # type: ignore[import]

    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    await acquire_alpaca_trading()
    async with api_call_span("alpaca_trading", "place_market_order", symbol=symbol, side=side):
        client = _trading_client()
        order = client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
        )

    return {
        "order_id": str(order.id),
        "status": str(order.status),
        "symbol": order.symbol,
        "qty": float(order.qty or 0),
        "side": str(order.side).lower(),
        "type": "market",
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
    }


async def place_limit_order(symbol: str, qty: float, side: str, limit_price: float) -> dict:
    """Place a limit order. NOT retried on failure — orders are not idempotent.

    Args:
        symbol: Ticker symbol.
        qty: Number of shares (fractional supported).
        side: 'buy' or 'sell'.
        limit_price: Limit price per share.

    Returns:
        dict with 'order_id', 'status', 'symbol', 'qty', 'side', 'type', 'limit_price', 'submitted_at'.
    """
    from alpaca.trading.requests import LimitOrderRequest  # type: ignore[import]
    from alpaca.trading.enums import OrderSide, TimeInForce  # type: ignore[import]

    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    await acquire_alpaca_trading()
    async with api_call_span("alpaca_trading", "place_limit_order", symbol=symbol, side=side):
        client = _trading_client()
        order = client.submit_order(
            LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.GTC,
                limit_price=limit_price,
            )
        )

    return {
        "order_id": str(order.id),
        "status": str(order.status),
        "symbol": order.symbol,
        "qty": float(order.qty or 0),
        "side": str(order.side).lower(),
        "type": "limit",
        "limit_price": limit_price,
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
    }


@with_retry
async def cancel_order(order_id: str) -> dict:
    """Cancel an open order by ID.

    Args:
        order_id: Alpaca order UUID string.

    Returns:
        dict with 'order_id', 'cancelled', 'message'.
    """
    await acquire_alpaca_trading()
    async with api_call_span("alpaca_trading", "cancel_order", order_id=order_id):
        client = _trading_client()
        try:
            client.cancel_order_by_id(order_id)
            return {"order_id": order_id, "cancelled": True, "message": "Order cancelled"}
        except Exception as exc:
            return {"order_id": order_id, "cancelled": False, "message": str(exc)}


@with_retry
async def get_order_status(order_id: str) -> dict:
    """Get current status of an order.

    Args:
        order_id: Alpaca order UUID string.

    Returns:
        dict with 'order_id', 'status', 'filled_qty', 'filled_avg_price', 'updated_at'.
    """
    await acquire_alpaca_trading()
    async with api_call_span("alpaca_trading", "get_order_status", order_id=order_id):
        client = _trading_client()
        order = client.get_order_by_id(order_id)

    return {
        "order_id": str(order.id),
        "status": str(order.status),
        "filled_qty": float(order.filled_qty or 0),
        "filled_avg_price": float(order.filled_avg_price or 0),
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


@with_retry
async def get_account_status() -> dict:
    """Check Alpaca account health — buying power, day trade count, margin status.

    Returns:
        dict with 'is_paper', 'status', 'buying_power', 'cash', 'portfolio_value',
                  'daytrade_count', 'pattern_day_trader'.
    """
    await acquire_alpaca_trading()
    async with api_call_span("alpaca_trading", "get_account"):
        account = _trading_client().get_account()

    return {
        "is_paper": True,
        "status": str(account.status),
        "buying_power": float(account.buying_power),
        "cash": float(account.cash),
        "portfolio_value": float(account.portfolio_value),
        "daytrade_count": int(account.daytrade_count or 0),
        "pattern_day_trader": bool(account.pattern_day_trader),
    }
