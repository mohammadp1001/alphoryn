"""Unit tests for agent.execution_agent — ExecutionAgent, _execute_alpaca, _execute_oanda."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeSession:
    def __init__(self):
        self.state = {}


class _FakeCtx:
    def __init__(self):
        self.session = _FakeSession()


def _make_pending_order_dict(**kwargs):
    defaults = {
        "symbol": "XLK",
        "side": "buy",
        "asset_class": "etf",
        "order_type": "market",
        "qty": 10.0,
    }
    defaults.update(kwargs)
    return defaults


async def _collect(gen):
    events = []
    async for event in gen:
        events.append(event)
    return events


def _make_alpaca_sys_modules(mock_client):
    mock_client_cls = MagicMock(return_value=mock_client)
    trading_client_mod = MagicMock(TradingClient=mock_client_cls)
    return {
        "alpaca.trading.client": trading_client_mod,
        "alpaca.trading.enums": MagicMock(),
        "alpaca.trading.requests": MagicMock(),
    }, mock_client_cls


def _make_alpaca_order(order_id="alp-1", symbol="XLK", qty="10.0"):
    o = MagicMock()
    o.id = order_id
    o.status = MagicMock()
    o.status.__str__ = lambda self: "submitted"
    o.symbol = symbol
    o.qty = qty
    o.limit_price = None
    o.submitted_at = None
    return o


# ── _run_async_impl ───────────────────────────────────────────────────────────

def test_run_async_impl_missing_pending_order():
    from agent.execution_agent import create_execution_agent
    agent = create_execution_agent()
    ctx = _FakeCtx()

    events = asyncio.run(_collect(agent._run_async_impl(ctx)))

    assert len(events) == 1
    assert ctx.session.state["order_result"]["status"] == "failed"
    assert "pending_order missing" in ctx.session.state["order_result"]["error"]


def test_run_async_impl_invalid_pending_order():
    from agent.execution_agent import create_execution_agent
    agent = create_execution_agent()
    ctx = _FakeCtx()
    ctx.session.state["pending_order"] = {"symbol": "X"}  # missing required fields

    events = asyncio.run(_collect(agent._run_async_impl(ctx)))

    assert len(events) == 1
    assert ctx.session.state["order_result"]["status"] == "failed"
    assert "invalid pending_order" in ctx.session.state["order_result"]["error"]


def test_run_async_impl_etf_routes_to_alpaca():
    from agent.execution_agent import create_execution_agent
    agent = create_execution_agent()
    ctx = _FakeCtx()
    ctx.session.state["pending_order"] = _make_pending_order_dict(asset_class="etf")

    mock_result = {"order_id": "alp-123", "status": "submitted", "symbol": "XLK",
                   "qty": 10.0, "side": "buy", "type": "market"}
    with patch("agent.execution_agent._execute_alpaca", new=AsyncMock(return_value=mock_result)):
        events = asyncio.run(_collect(agent._run_async_impl(ctx)))

    assert ctx.session.state["order_result"]["order_id"] == "alp-123"
    assert len(events) == 1


def test_run_async_impl_crypto_routes_to_alpaca():
    from agent.execution_agent import create_execution_agent
    agent = create_execution_agent()
    ctx = _FakeCtx()
    ctx.session.state["pending_order"] = _make_pending_order_dict(asset_class="crypto", symbol="BTCUSD")

    mock_result = {"order_id": "crypto-1", "status": "submitted", "symbol": "BTCUSD",
                   "qty": 1.0, "side": "buy", "type": "market"}
    with patch("agent.execution_agent._execute_alpaca", new=AsyncMock(return_value=mock_result)):
        events = asyncio.run(_collect(agent._run_async_impl(ctx)))

    assert ctx.session.state["order_result"]["order_id"] == "crypto-1"


def test_run_async_impl_forex_routes_to_oanda():
    from agent.execution_agent import create_execution_agent
    agent = create_execution_agent()
    ctx = _FakeCtx()
    ctx.session.state["pending_order"] = _make_pending_order_dict(
        asset_class="forex", symbol="EUR_USD"
    )

    mock_result = {"order_id": "oanda-1", "status": "FILLED"}
    with patch("agent.execution_agent._execute_oanda", new=AsyncMock(return_value=mock_result)):
        events = asyncio.run(_collect(agent._run_async_impl(ctx)))

    assert ctx.session.state["order_result"]["order_id"] == "oanda-1"


def test_run_async_impl_unknown_asset_class():
    from agent.execution_agent import create_execution_agent
    agent = create_execution_agent()
    ctx = _FakeCtx()
    ctx.session.state["pending_order"] = _make_pending_order_dict(asset_class="commodity")

    events = asyncio.run(_collect(agent._run_async_impl(ctx)))

    assert ctx.session.state["order_result"]["status"] == "failed"
    assert "unknown asset_class" in ctx.session.state["order_result"]["error"]


# ── _execute_alpaca ───────────────────────────────────────────────────────────

def test_execute_alpaca_missing_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    from agent.execution_agent import _execute_alpaca
    from tools.schemas import PendingOrder

    order = PendingOrder(symbol="XLK", side="buy", asset_class="etf", order_type="market", qty=10.0)
    result = asyncio.run(_execute_alpaca(order))

    assert result["status"] == "failed"
    assert "ALPACA_API_KEY" in result["error"]


def test_execute_alpaca_market_order_success(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    from agent.execution_agent import _execute_alpaca
    from tools.schemas import PendingOrder

    mock_order = _make_alpaca_order()
    mock_client = MagicMock()
    mock_client.submit_order.return_value = mock_order
    sys_mods, _ = _make_alpaca_sys_modules(mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="XLK", side="buy", asset_class="etf", order_type="market", qty=10.0)
        result = asyncio.run(_execute_alpaca(order))

    assert result["status"] == "submitted"
    assert result["symbol"] == "XLK"


def test_execute_alpaca_market_order_sell(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    from agent.execution_agent import _execute_alpaca
    from tools.schemas import PendingOrder

    mock_order = _make_alpaca_order()
    mock_client = MagicMock()
    mock_client.submit_order.return_value = mock_order
    sys_mods, _ = _make_alpaca_sys_modules(mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="XLK", side="sell", asset_class="etf", order_type="market", qty=5.0)
        result = asyncio.run(_execute_alpaca(order))

    assert result["status"] == "submitted"


def test_execute_alpaca_limit_order_success(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    from agent.execution_agent import _execute_alpaca
    from tools.schemas import PendingOrder

    mock_order = _make_alpaca_order()
    mock_order.limit_price = "185.50"
    mock_client = MagicMock()
    mock_client.submit_order.return_value = mock_order
    sys_mods, _ = _make_alpaca_sys_modules(mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(
            symbol="XLK", side="buy", asset_class="etf",
            order_type="limit", qty=10.0, limit_price=185.5,
        )
        result = asyncio.run(_execute_alpaca(order))

    assert result["status"] == "submitted"
    assert result["limit_price"] == pytest.approx(185.5)


def test_execute_alpaca_qty_auto_computed(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    from agent.execution_agent import _execute_alpaca
    from tools.schemas import PendingOrder

    mock_order = _make_alpaca_order()
    mock_account = MagicMock()
    mock_account.buying_power = "5000.0"

    mock_client = MagicMock()
    mock_client.submit_order.return_value = mock_order
    mock_client.get_account.return_value = mock_account
    sys_mods, _ = _make_alpaca_sys_modules(mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch("agent.execution_agent._get_last_price", return_value=100.0),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(
            symbol="XLK", side="buy", asset_class="etf",
            order_type="market", qty=None, buying_power_pct=0.1,
        )
        result = asyncio.run(_execute_alpaca(order))

    assert result["status"] == "submitted"


def test_execute_alpaca_qty_none_no_price(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    from agent.execution_agent import _execute_alpaca
    from tools.schemas import PendingOrder

    mock_account = MagicMock()
    mock_account.buying_power = "5000.0"

    mock_client = MagicMock()
    mock_client.get_account.return_value = mock_account
    sys_mods, _ = _make_alpaca_sys_modules(mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch("agent.execution_agent._get_last_price", return_value=None),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="XLK", side="buy", asset_class="etf",
                             order_type="market", qty=None)
        result = asyncio.run(_execute_alpaca(order))

    assert result["status"] == "failed"
    assert "could not determine price" in result["error"]


def test_execute_alpaca_exception(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    from agent.execution_agent import _execute_alpaca
    from tools.schemas import PendingOrder

    trading_client_mod = MagicMock(TradingClient=MagicMock(side_effect=RuntimeError("broker down")))
    sys_mods = {
        "alpaca.trading.client": trading_client_mod,
        "alpaca.trading.enums": MagicMock(),
        "alpaca.trading.requests": MagicMock(),
    }

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="XLK", side="buy", asset_class="etf",
                             order_type="market", qty=5.0)
        result = asyncio.run(_execute_alpaca(order))

    assert result["status"] == "failed"
    assert "broker_error" in result["error"]


# ── _get_last_price ───────────────────────────────────────────────────────────

def test_get_last_price_success():
    from agent.execution_agent import _get_last_price

    mock_quote = MagicMock()
    mock_quote.ask_price = 1.06
    mock_quote.bid_price = 1.04

    mock_data_client = MagicMock()
    mock_data_client.get_stock_latest_quote.return_value = {"XLK": mock_quote}

    mock_hist_cls = MagicMock(return_value=mock_data_client)
    mock_req_cls = MagicMock()

    sys_mods = {
        "alpaca.data.historical": MagicMock(StockHistoricalDataClient=mock_hist_cls),
        "alpaca.data.requests": MagicMock(StockLatestQuoteRequest=mock_req_cls),
    }

    with patch.dict("sys.modules", sys_mods):
        result = _get_last_price("XLK", MagicMock())

    assert result == pytest.approx(1.05)


def test_get_last_price_symbol_not_in_response():
    from agent.execution_agent import _get_last_price

    mock_data_client = MagicMock()
    mock_data_client.get_stock_latest_quote.return_value = {}  # symbol missing

    mock_hist_cls = MagicMock(return_value=mock_data_client)
    sys_mods = {
        "alpaca.data.historical": MagicMock(StockHistoricalDataClient=mock_hist_cls),
        "alpaca.data.requests": MagicMock(),
    }

    with patch.dict("sys.modules", sys_mods):
        result = _get_last_price("XLK", MagicMock())

    assert result is None


def test_get_last_price_exception_returns_none():
    from agent.execution_agent import _get_last_price

    sys_mods = {
        "alpaca.data.historical": MagicMock(
            StockHistoricalDataClient=MagicMock(side_effect=RuntimeError("no data"))
        ),
        "alpaca.data.requests": MagicMock(),
    }

    with patch.dict("sys.modules", sys_mods):
        result = _get_last_price("XLK", MagicMock())

    assert result is None


# ── _execute_oanda ────────────────────────────────────────────────────────────

def _make_oanda_sys_modules(mock_endpoint, mock_client):
    mock_oanda_mod = MagicMock()
    mock_oanda_mod.API.return_value = mock_client
    mock_endpoints_orders = MagicMock(OrderCreate=MagicMock(return_value=mock_endpoint))
    return {
        "oandapyV20": mock_oanda_mod,
        "oandapyV20.endpoints": MagicMock(),
        "oandapyV20.endpoints.orders": mock_endpoints_orders,
    }


def test_execute_oanda_missing_credentials(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)

    from agent.execution_agent import _execute_oanda
    from tools.schemas import PendingOrder

    order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                         order_type="market", qty=1000.0)
    result = asyncio.run(_execute_oanda(order))

    assert result["status"] == "failed"
    assert "OANDA_API_TOKEN" in result["error"]


def test_execute_oanda_market_order_filled(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999-001")

    from agent.execution_agent import _execute_oanda
    from tools.schemas import PendingOrder

    mock_endpoint = MagicMock()
    mock_endpoint.response = {
        "orderFillTransaction": {
            "orderID": "oanda-fill-1",
            "price": "1.0850",
            "time": "2026-06-10T10:00:00Z",
        }
    }
    mock_client = MagicMock()
    sys_mods = _make_oanda_sys_modules(mock_endpoint, mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="market", qty=1000.0)
        result = asyncio.run(_execute_oanda(order))

    assert result["status"] == "FILLED"
    assert result["order_id"] == "oanda-fill-1"


def test_execute_oanda_limit_order_pending(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999-001")

    from agent.execution_agent import _execute_oanda
    from tools.schemas import PendingOrder

    mock_endpoint = MagicMock()
    mock_endpoint.response = {
        "orderCreateTransaction": {"id": "oanda-limit-1", "time": "2026-06-10T10:00:00Z"},
    }
    mock_client = MagicMock()
    sys_mods = _make_oanda_sys_modules(mock_endpoint, mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="limit", qty=1000.0, limit_price=1.0800)
        result = asyncio.run(_execute_oanda(order))

    assert result["status"] == "PENDING"
    assert result["order_id"] == "oanda-limit-1"


def test_execute_oanda_order_cancelled(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999-001")

    from agent.execution_agent import _execute_oanda
    from tools.schemas import PendingOrder

    mock_endpoint = MagicMock()
    mock_endpoint.response = {
        "orderCancelTransaction": {"reason": "INSUFFICIENT_MARGIN"},
    }
    mock_client = MagicMock()
    sys_mods = _make_oanda_sys_modules(mock_endpoint, mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="EUR_USD", side="sell", asset_class="forex",
                             order_type="market", qty=500.0)
        result = asyncio.run(_execute_oanda(order))

    assert result["status"] == "failed"
    assert "INSUFFICIENT_MARGIN" in result["error"]


def test_execute_oanda_order_cancelled_unknown_reason(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999-001")

    from agent.execution_agent import _execute_oanda
    from tools.schemas import PendingOrder

    mock_endpoint = MagicMock()
    mock_endpoint.response = {}  # no fill, no create, no cancel → else branch
    mock_client = MagicMock()
    sys_mods = _make_oanda_sys_modules(mock_endpoint, mock_client)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="market", qty=1000.0)
        result = asyncio.run(_execute_oanda(order))

    assert result["status"] == "failed"
    assert "unknown" in result["error"]


def test_execute_oanda_exception(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999-001")

    from agent.execution_agent import _execute_oanda
    from tools.schemas import PendingOrder

    mock_oanda = MagicMock()
    mock_oanda.API.side_effect = RuntimeError("oanda down")
    sys_mods = {
        "oandapyV20": mock_oanda,
        "oandapyV20.endpoints": MagicMock(),
        "oandapyV20.endpoints.orders": MagicMock(),
    }

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", sys_mods),
    ):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="market", qty=1000.0)
        result = asyncio.run(_execute_oanda(order))

    assert result["status"] == "failed"
    assert "broker_error" in result["error"]


# ── _forex_units ──────────────────────────────────────────────────────────────

def test_forex_units_buy_with_explicit_qty():
    from agent.execution_agent import _forex_units
    from tools.schemas import PendingOrder

    order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                         order_type="market", qty=1000.0)
    result = _forex_units(order, MagicMock(), "account-1")

    assert result == 1000


def test_forex_units_sell_with_explicit_qty():
    from agent.execution_agent import _forex_units
    from tools.schemas import PendingOrder

    order = PendingOrder(symbol="EUR_USD", side="sell", asset_class="forex",
                         order_type="market", qty=500.0)
    result = _forex_units(order, MagicMock(), "account-1")

    assert result == -500


def test_forex_units_auto_size_from_nav():
    from agent.execution_agent import _forex_units
    from tools.schemas import PendingOrder

    mock_endpoint = MagicMock()
    mock_endpoint.response = {"account": {"NAV": "10000.0"}}
    mock_account_details_cls = MagicMock(return_value=mock_endpoint)
    mock_client = MagicMock()

    sys_mods = {
        "oandapyV20.endpoints.accounts": MagicMock(AccountDetails=mock_account_details_cls),
    }

    with patch.dict("sys.modules", sys_mods):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="market", qty=None, buying_power_pct=0.05)
        result = _forex_units(order, mock_client, "account-1")

    assert result is not None
    assert result > 0


def test_forex_units_auto_size_sell_negative():
    from agent.execution_agent import _forex_units
    from tools.schemas import PendingOrder

    mock_endpoint = MagicMock()
    mock_endpoint.response = {"account": {"NAV": "10000.0"}}
    mock_account_details_cls = MagicMock(return_value=mock_endpoint)
    mock_client = MagicMock()

    sys_mods = {
        "oandapyV20.endpoints.accounts": MagicMock(AccountDetails=mock_account_details_cls),
    }

    with patch.dict("sys.modules", sys_mods):
        order = PendingOrder(symbol="EUR_USD", side="sell", asset_class="forex",
                             order_type="market", qty=None, buying_power_pct=0.05)
        result = _forex_units(order, mock_client, "account-1")

    assert result is not None
    assert result < 0


def test_forex_units_zero_nav_returns_none():
    from agent.execution_agent import _forex_units
    from tools.schemas import PendingOrder

    mock_endpoint = MagicMock()
    mock_endpoint.response = {"account": {"NAV": "0"}}
    mock_account_details_cls = MagicMock(return_value=mock_endpoint)
    mock_client = MagicMock()

    sys_mods = {
        "oandapyV20.endpoints.accounts": MagicMock(AccountDetails=mock_account_details_cls),
    }

    with patch.dict("sys.modules", sys_mods):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="market", qty=None)
        result = _forex_units(order, mock_client, "account-1")

    assert result is None


def test_forex_units_exception_returns_none():
    from agent.execution_agent import _forex_units
    from tools.schemas import PendingOrder

    mock_client = MagicMock()
    mock_client.request.side_effect = RuntimeError("network error")
    mock_account_details_cls = MagicMock()

    sys_mods = {
        "oandapyV20.endpoints.accounts": MagicMock(AccountDetails=mock_account_details_cls),
    }

    with patch.dict("sys.modules", sys_mods):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="market", qty=None)
        result = _forex_units(order, mock_client, "account-1")

    assert result is None


# ── _error_result ─────────────────────────────────────────────────────────────

def test_error_result_structure():
    from agent.execution_agent import _error_result

    result = _error_result("XLK", "something went wrong")

    assert result["status"] == "failed"
    assert result["symbol"] == "XLK"
    assert result["error"] == "something went wrong"
    assert result["order_id"] == ""
    assert result["qty"] == 0.0


def test_execute_oanda_forex_units_returns_none(monkeypatch):
    """Line 180: when _forex_units returns None, _error_result is returned."""
    monkeypatch.setenv("OANDA_API_TOKEN", "token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999-001")

    from agent.execution_agent import _execute_oanda
    from tools.schemas import PendingOrder

    mock_oanda_mod = MagicMock()
    mock_oanda_mod.API.return_value = MagicMock()

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch.dict("sys.modules", {
            "oandapyV20": mock_oanda_mod,
            "oandapyV20.endpoints": MagicMock(),
            "oandapyV20.endpoints.orders": MagicMock(),
        }),
        patch("agent.execution_agent._forex_units", return_value=None),
    ):
        order = PendingOrder(symbol="EUR_USD", side="buy", asset_class="forex",
                             order_type="market", qty=None)
        result = asyncio.run(_execute_oanda(order))

    assert result["status"] == "failed"
    assert "units" in result["error"]
