"""Unit tests for tools.forex — OANDA market-data tools (mocked API)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

# ── Schema tests (no I/O) ─────────────────────────────────────────────────────

def test_forex_account_status_schema():
    from tools.schemas import ForexAccountStatus
    obj = ForexAccountStatus(
        account_id="001-001-1234567-001",
        balance=10000.0,
        nav=10050.0,
        unrealized_pl=50.0,
        margin_used=200.0,
        margin_available=9850.0,
        open_position_count=2,
        currency="EUR",
        is_practice=True,
    )
    d = obj.model_dump()
    assert d["account_id"] == "001-001-1234567-001"
    assert d["is_practice"] is True
    assert d["currency"] == "EUR"


def test_forex_position_schema():
    from tools.schemas import ForexPosition, ForexPositionSide
    pos = ForexPosition(
        instrument="EUR_USD",
        long=ForexPositionSide(units=1000, avg_price=1.0850, unrealized_pl=25.0),
        short=None,
        net_units=1000,
        unrealized_pl=25.0,
    )
    d = pos.model_dump()
    assert d["instrument"] == "EUR_USD"
    assert d["net_units"] == 1000
    assert d["long"]["units"] == 1000
    assert d["short"] is None


def test_forex_order_result_schema():
    from tools.schemas import ForexOrderResult
    result = ForexOrderResult(
        order_id="12345",
        status="FILLED",
        instrument="EUR_USD",
        units=1000,
        fill_price=1.0852,
        time_in_force="FOK",
        submitted_at="2026-06-10T10:00:00.000000Z",
    )
    d = result.model_dump()
    assert d["status"] == "FILLED"
    assert d["units"] == 1000
    assert d["error"] is None


def test_forex_order_result_finite_float_guards_nan():

    from tools.schemas import ForexOrderResult
    result = ForexOrderResult(
        order_id="x",
        status="FILLED",
        instrument="GBP_USD",
        units=-500,
        fill_price=float("nan"),
        time_in_force="FOK",
    )
    assert result.fill_price is None


def test_forex_position_close_result_schema():
    from tools.schemas import ForexPositionCloseResult
    result = ForexPositionCloseResult(
        instrument="USD_JPY",
        closed=True,
        long_units_closed=1000,
        short_units_closed=0,
        realized_pl=12.50,
    )
    d = result.model_dump()
    assert d["closed"] is True
    assert d["realized_pl"] == 12.50


def test_forex_prices_response_schema():
    from tools.schemas import ForexPrice, ForexPricesResponse
    resp = ForexPricesResponse(
        prices=[
            ForexPrice(instrument="EUR_USD", bid=1.0849, ask=1.0851, mid=1.0850, tradeable=True),
            ForexPrice(instrument="GBP_USD", bid=1.2699, ask=1.2701, mid=1.2700, tradeable=True),
        ]
    )
    d = resp.model_dump()
    assert len(d["prices"]) == 2
    assert d["prices"][0]["instrument"] == "EUR_USD"


# ── Module import tests ───────────────────────────────────────────────────────

def test_forex_tools_importable():
    from tools.forex.tools import (
        get_forex_account,
        get_forex_instruments,
        get_forex_positions,
        get_forex_prices,
    )
    assert get_forex_account is not None
    assert get_forex_positions is not None
    assert get_forex_prices is not None
    assert get_forex_instruments is not None


def test_forex_tools_are_coroutines():
    import asyncio

    from tools.forex.tools import (
        get_forex_account,
        get_forex_instruments,
        get_forex_positions,
        get_forex_prices,
    )
    assert asyncio.iscoroutinefunction(get_forex_account)
    assert asyncio.iscoroutinefunction(get_forex_positions)
    assert asyncio.iscoroutinefunction(get_forex_prices)
    assert asyncio.iscoroutinefunction(get_forex_instruments)


# ── Behaviour tests (mocked oandapyV20) ──────────────────────────────────────

def _make_oanda_mock(response: dict):
    """Return a mock oandapyV20.API whose .request() populates r.response."""
    def fake_request(r):
        r.response = response
    client = MagicMock()
    client.request.side_effect = fake_request
    return client


def test_get_forex_account_returns_expected_fields(monkeypatch):
    import asyncio

    from tools.forex import tools as forex_module

    fake_resp = {
        "account": {
            "id": "001-001-9999999-001",
            "balance": "10000.0000",
            "NAV": "10050.5000",
            "unrealizedPL": "50.5000",
            "marginUsed": "200.0000",
            "marginAvailable": "9850.5000",
            "openPositionCount": 1,
            "currency": "EUR",
        }
    }

    mock_client = _make_oanda_mock(fake_resp)

    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999999-001")

    with (
        patch("tools.forex.tools._oanda_client", return_value=(mock_client, "001-001-9999999-001")),
        patch("tools.forex.tools.acquire_oanda", return_value=None),
    ):
        result = asyncio.run(forex_module.get_forex_account())

    assert result["account_id"] == "001-001-9999999-001"
    assert result["currency"] == "EUR"
    assert result["is_practice"] is True
    assert result["open_position_count"] == 1


def test_get_forex_positions_empty(monkeypatch):
    import asyncio

    from tools.forex import tools as forex_module

    fake_resp = {"positions": []}
    mock_client = _make_oanda_mock(fake_resp)

    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999999-001")

    with (
        patch("tools.forex.tools._oanda_client", return_value=(mock_client, "001-001-9999999-001")),
        patch("tools.forex.tools.acquire_oanda", return_value=None),
    ):
        result = asyncio.run(forex_module.get_forex_positions())

    assert result["positions"] == []
    assert result["account_id"] == "001-001-9999999-001"


def test_get_forex_positions_with_long_position(monkeypatch):
    import asyncio

    from tools.forex import tools as forex_module

    fake_resp = {
        "positions": [
            {
                "instrument": "EUR_USD",
                "long": {"units": "1000", "averagePrice": "1.0850", "unrealizedPL": "25.00"},
                "short": {"units": "0", "averagePrice": "0", "unrealizedPL": "0"},
                "unrealizedPL": "25.00",
            }
        ]
    }
    mock_client = _make_oanda_mock(fake_resp)

    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999999-001")

    with (
        patch("tools.forex.tools._oanda_client", return_value=(mock_client, "001-001-9999999-001")),
        patch("tools.forex.tools.acquire_oanda", return_value=None),
    ):
        result = asyncio.run(forex_module.get_forex_positions())

    assert len(result["positions"]) == 1
    pos = result["positions"][0]
    assert pos["instrument"] == "EUR_USD"
    assert pos["net_units"] == 1000


def test_get_forex_prices_returns_bid_ask(monkeypatch):
    import asyncio

    from tools.forex import tools as forex_module

    fake_resp = {
        "prices": [
            {
                "instrument": "EUR_USD",
                "bids": [{"price": "1.0849", "liquidity": 10000000}],
                "asks": [{"price": "1.0851", "liquidity": 10000000}],
                "tradeable": True,
            }
        ]
    }
    mock_client = _make_oanda_mock(fake_resp)

    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999999-001")

    with (
        patch("tools.forex.tools._oanda_client", return_value=(mock_client, "001-001-9999999-001")),
        patch("tools.forex.tools.acquire_oanda", return_value=None),
    ):
        result = asyncio.run(forex_module.get_forex_prices(["EUR_USD"]))

    assert len(result["prices"]) == 1
    price = result["prices"][0]
    assert price["instrument"] == "EUR_USD"
    assert abs(price["mid"] - 1.0850) < 1e-5
    assert price["tradeable"] is True


def test_get_forex_instruments_returns_list(monkeypatch):
    import asyncio

    from tools.forex import tools as forex_module

    fake_resp = {
        "instruments": [
            {
                "name": "EUR_USD",
                "displayName": "EUR/USD",
                "pipLocation": -4,
                "marginRate": "0.02",
            },
            {
                "name": "GBP_USD",
                "displayName": "GBP/USD",
                "pipLocation": -4,
                "marginRate": "0.02",
            },
        ]
    }
    mock_client = _make_oanda_mock(fake_resp)

    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-001-9999999-001")

    with (
        patch("tools.forex.tools._oanda_client", return_value=(mock_client, "001-001-9999999-001")),
        patch("tools.forex.tools.acquire_oanda", return_value=None),
    ):
        result = asyncio.run(forex_module.get_forex_instruments())

    assert len(result["instruments"]) == 2
    assert result["instruments"][0]["name"] == "EUR_USD"
    assert result["instruments"][0]["pip_location"] == -4


def test_oanda_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)

    import pytest
    with pytest.raises(RuntimeError, match="OANDA_API_TOKEN"):
        from tools.forex.tools import _oanda_client
        _oanda_client()
