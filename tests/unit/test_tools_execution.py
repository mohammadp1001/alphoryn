"""Unit tests for tools.execution.tools — Alpaca trading tools."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_acquire():
    return patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock())


def _make_position(symbol="XLK", qty="10", side="long", avg_entry="185.0",
                   market_value="1850.0", pl="-5.0", plpc="-0.0027"):
    p = MagicMock()
    p.symbol = symbol
    p.qty = qty
    p.side = MagicMock()
    p.side.__str__ = lambda self: "long"
    p.avg_entry_price = avg_entry
    p.market_value = market_value
    p.unrealized_pl = pl
    p.unrealized_plpc = plpc
    return p


def _make_account(cash="5000.0", portfolio_value="10000.0", buying_power="5000.0",
                  status="ACTIVE", daytrade_count=0, pdt=False):
    a = MagicMock()
    a.cash = cash
    a.portfolio_value = portfolio_value
    a.buying_power = buying_power
    a.status = MagicMock()
    a.status.__str__ = lambda self: status
    a.daytrade_count = daytrade_count
    a.pattern_day_trader = pdt
    return a


def _make_order(order_id="order-1", status="submitted", symbol="XLK",
                qty="10", side="buy", filled_qty="0", filled_price=None,
                submitted_at=None, updated_at=None):
    o = MagicMock()
    o.id = order_id
    o.status = MagicMock()
    o.status.__str__ = lambda self: status
    o.symbol = symbol
    o.qty = qty
    o.side = MagicMock()
    o.side.__str__ = lambda self: side
    o.filled_qty = filled_qty
    o.filled_avg_price = filled_price
    o.submitted_at = submitted_at or datetime(2025, 1, 1, tzinfo=timezone.utc)
    o.updated_at = updated_at
    return o


# ── get_portfolio ─────────────────────────────────────────────────────────────

def test_get_portfolio_returns_correct_structure(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    account = _make_account()
    positions = [_make_position("XLK"), _make_position("SPY", qty="5")]

    mock_client = MagicMock()
    mock_client.get_account.return_value = account
    mock_client.get_all_positions.return_value = positions

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import get_portfolio
            result = asyncio.run(get_portfolio())

    assert "positions" in result
    assert len(result["positions"]) == 2
    assert result["is_paper"] is True
    assert "cash_usd" in result
    assert "portfolio_value" in result
    assert "buying_power" in result


def test_get_portfolio_position_fields(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    account = _make_account()
    positions = [_make_position("QQQ", qty="3", avg_entry="400.0",
                                market_value="1200.0", pl="30.0", plpc="0.025")]

    mock_client = MagicMock()
    mock_client.get_account.return_value = account
    mock_client.get_all_positions.return_value = positions

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import get_portfolio
            result = asyncio.run(get_portfolio())

    pos = result["positions"][0]
    assert pos["symbol"] == "QQQ"
    assert pos["qty"] == 3.0
    assert pos["avg_entry_price"] == 400.0
    assert abs(pos["unrealised_pnl_pct"] - 2.5) < 0.01


# ── get_position ──────────────────────────────────────────────────────────────

def test_get_position_has_position(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    pos = _make_position("XLE", qty="8", avg_entry="90.0",
                         market_value="720.0", pl="0.0", plpc="0.0")

    mock_client = MagicMock()
    mock_client.get_open_position.return_value = pos

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import get_position
            result = asyncio.run(get_position("XLE"))

    assert result["has_position"] is True
    assert result["symbol"] == "XLE"
    assert result["qty"] == 8.0


def test_get_position_no_position(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    mock_client = MagicMock()
    mock_client.get_open_position.side_effect = Exception("position not found")

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import get_position
            result = asyncio.run(get_position("NOPE"))

    assert result["has_position"] is False
    assert result["symbol"] == "NOPE"


# ── place_market_order ────────────────────────────────────────────────────────

def test_place_market_order_buy(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    order = _make_order(order_id="mkt-1", symbol="XLK", qty="10", side="buy")

    mock_client = MagicMock()
    mock_client.submit_order.return_value = order

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import place_market_order
            result = asyncio.run(place_market_order("XLK", 10.0, "buy"))

    assert result["order_id"] == "mkt-1"
    assert result["type"] == "market"
    assert result["symbol"] == "XLK"
    assert result["side"] == "buy"


def test_place_market_order_sell(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    order = _make_order(order_id="mkt-2", symbol="SPY", qty="5", side="sell")

    mock_client = MagicMock()
    mock_client.submit_order.return_value = order

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import place_market_order
            result = asyncio.run(place_market_order("SPY", 5.0, "sell"))

    assert result["side"] == "sell"
    assert result["submitted_at"] is not None


def test_place_market_order_submitted_at_none(monkeypatch):
    """Handle order with submitted_at=None."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    order = _make_order(symbol="XLK", submitted_at=None)
    order.submitted_at = None

    mock_client = MagicMock()
    mock_client.submit_order.return_value = order

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import place_market_order
            result = asyncio.run(place_market_order("XLK", 1.0, "buy"))

    assert result["submitted_at"] is None


# ── place_limit_order ─────────────────────────────────────────────────────────

def test_place_limit_order(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    order = _make_order(order_id="lim-1", symbol="QQQ", qty="3", side="buy")

    mock_client = MagicMock()
    mock_client.submit_order.return_value = order

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import place_limit_order
            result = asyncio.run(place_limit_order("QQQ", 3.0, "buy", 399.50))

    assert result["type"] == "limit"
    assert result["limit_price"] == 399.50
    assert result["order_id"] == "lim-1"


def test_place_limit_order_sell(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    order = _make_order(order_id="lim-2", symbol="IWM", qty="2", side="sell")

    mock_client = MagicMock()
    mock_client.submit_order.return_value = order

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import place_limit_order
            result = asyncio.run(place_limit_order("IWM", 2.0, "sell", 210.0))

    assert result["type"] == "limit"
    assert result["side"] == "sell"


# ── cancel_order ──────────────────────────────────────────────────────────────

def test_cancel_order_success(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    mock_client = MagicMock()
    mock_client.cancel_order_by_id.return_value = None  # success

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import cancel_order
            result = asyncio.run(cancel_order("order-999"))

    assert result["cancelled"] is True
    assert result["order_id"] == "order-999"
    assert result["message"] == "Order cancelled"


def test_cancel_order_failure(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    mock_client = MagicMock()
    mock_client.cancel_order_by_id.side_effect = Exception("order not found")

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import cancel_order
            result = asyncio.run(cancel_order("bad-order"))

    assert result["cancelled"] is False
    assert "order not found" in result["message"]


# ── get_order_status ──────────────────────────────────────────────────────────

def test_get_order_status(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    order = _make_order(
        order_id="ord-status",
        status="filled",
        filled_qty="10",
        filled_price="185.5",
        updated_at=ts,
    )

    mock_client = MagicMock()
    mock_client.get_order_by_id.return_value = order

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import get_order_status
            result = asyncio.run(get_order_status("ord-status"))

    assert result["order_id"] == "ord-status"
    assert result["filled_qty"] == 10.0
    assert result["filled_avg_price"] == 185.5
    assert result["updated_at"] is not None


def test_get_order_status_null_fill_fields(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    order = _make_order(status="pending_new", filled_qty=None, filled_price=None, updated_at=None)
    order.filled_qty = None
    order.filled_avg_price = None
    order.updated_at = None

    mock_client = MagicMock()
    mock_client.get_order_by_id.return_value = order

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import get_order_status
            result = asyncio.run(get_order_status("ord-new"))

    assert result["filled_qty"] == 0.0
    assert result["filled_avg_price"] == 0.0
    assert result["updated_at"] is None


# ── get_account_status ────────────────────────────────────────────────────────

def test_get_account_status(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    account = _make_account(
        cash="3000.0",
        portfolio_value="8000.0",
        buying_power="3000.0",
        status="ACTIVE",
        daytrade_count=1,
        pdt=False,
    )

    mock_client = MagicMock()
    mock_client.get_account.return_value = account

    with _mock_acquire():
        with patch("tools.execution.tools._trading_client", return_value=mock_client):
            from tools.execution.tools import get_account_status
            result = asyncio.run(get_account_status())

    assert result["is_paper"] is True
    assert result["buying_power"] == 3000.0
    assert result["cash"] == 3000.0
    assert result["portfolio_value"] == 8000.0
    assert result["daytrade_count"] == 1
    assert result["pattern_day_trader"] is False


# ── _trading_client factory ───────────────────────────────────────────────────

def test_trading_client_factory_returns_instance(monkeypatch):
    """Lines 20-22: _trading_client() builds a TradingClient from env vars."""
    monkeypatch.setenv("ALPACA_API_KEY", "fake-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "fake-secret")

    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)

    with patch.dict("sys.modules", {
        "alpaca": MagicMock(),
        "alpaca.trading": MagicMock(),
        "alpaca.trading.client": MagicMock(TradingClient=mock_cls),
    }):
        import importlib
        import tools.execution.tools as exec_tools
        importlib.reload(exec_tools)
        result = exec_tools._trading_client()

    mock_cls.assert_called_once_with(
        api_key="fake-key",
        secret_key="fake-secret",
        paper=True,
    )
    assert result is mock_instance
