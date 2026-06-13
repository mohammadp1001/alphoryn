"""Unit tests for tools.data — get_ohlcv, get_52w_range, _is_crypto."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

# ── _is_crypto ────────────────────────────────────────────────────────────────


def test_is_crypto_usd_suffix():
    from tools.data import _is_crypto

    assert _is_crypto("BTC-USD") is True


def test_is_crypto_stock():
    from tools.data import _is_crypto

    assert _is_crypto("SPY") is False


def test_is_crypto_non_usd_hyphen():
    from tools.data import _is_crypto

    assert _is_crypto("EWG") is False


# ── get_52w_range ─────────────────────────────────────────────────────────────


def _make_yf_info(high=200.0, low=100.0, price=150.0):
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = {
        "fiftyTwoWeekHigh": high,
        "fiftyTwoWeekLow": low,
        "regularMarketPrice": price,
    }
    return mock_yf


def test_get_52w_range_returns_expected_keys():
    mock_yf = _make_yf_info()
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.data import get_52w_range

        result = asyncio.run(get_52w_range("SPY"))

    assert result["symbol"] == "SPY"
    assert result["high_52w"] == 200.0
    assert result["low_52w"] == 100.0
    assert result["current_price"] == 150.0
    assert "pct_from_high" in result
    assert "pct_from_low" in result


def test_get_52w_range_zero_high_no_divide():
    mock_yf = _make_yf_info(high=0.0, low=0.0, price=0.0)
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.data import get_52w_range

        result = asyncio.run(get_52w_range("SPY"))

    assert result["pct_from_high"] == 0.0


def test_get_52w_range_uses_current_price_fallback():
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = {
        "fiftyTwoWeekHigh": 200.0,
        "fiftyTwoWeekLow": 100.0,
        "currentPrice": 160.0,
    }
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.data import get_52w_range

        result = asyncio.run(get_52w_range("SPY"))

    assert result["current_price"] == 160.0


# ── get_ohlcv ─────────────────────────────────────────────────────────────────


def _make_bar(close: float = 100.0):
    b = MagicMock()
    b.timestamp.isoformat.return_value = "2026-01-01T00:00:00"
    b.open = close - 1
    b.high = close + 1
    b.low = close - 2
    b.close = close
    b.volume = 1_000_000
    return b


def test_get_ohlcv_alpaca_path_returns_bars():
    bar = _make_bar(100.0)
    mock_resp = {"SPY": [bar]}

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("tools.data._data_client") as mock_dc,
        patch("tools.data._is_crypto", return_value=False),
        patch("tools.data.api_call_span"),
    ):
        mock_dc.return_value.get_stock_bars.return_value = mock_resp
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("SPY", "1Day", 1))

    assert result["symbol"] == "SPY"
    assert len(result["bars"]) == 1
    assert result["bars"][0]["close"] == 100.0


def test_get_ohlcv_crypto_path():
    bar = _make_bar(50000.0)
    mock_resp = {"BTC/USD": [bar]}

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("tools.data._crypto_client") as mock_cc,
        patch("tools.data._is_crypto", return_value=True),
        patch("tools.data.api_call_span"),
    ):
        mock_cc.return_value.get_crypto_bars.return_value = mock_resp
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("BTC-USD", "1Day", 1))

    assert result["symbol"] == "BTC-USD"
    assert len(result["bars"]) == 1


def test_get_ohlcv_falls_back_to_yfinance_when_alpaca_empty():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    hist = pd.DataFrame(
        {
            "Open": [99.0, 100.0, 101.0],
            "High": [102.0, 103.0, 104.0],
            "Low": [98.0, 99.0, 100.0],
            "Close": [100.0, 101.0, 102.0],
            "Volume": [1e6, 1e6, 1e6],
        },
        index=dates,
    )
    mock_yf = MagicMock()
    mock_yf.download.return_value = hist

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch("tools.data._data_client") as mock_dc,
        patch("tools.data._is_crypto", return_value=False),
        patch("tools.data.api_call_span"),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        mock_dc.return_value.get_stock_bars.return_value = {}
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("SPY", "1Day", 3))

    assert len(result["bars"]) == 3


def test_get_ohlcv_yfinance_empty_returns_empty_bars():
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame()

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch("tools.data._data_client") as mock_dc,
        patch("tools.data._is_crypto", return_value=False),
        patch("tools.data.api_call_span"),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        mock_dc.return_value.get_stock_bars.return_value = {}
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("SPY", "1Day", 5))

    assert result["bars"] == []


def test_data_client_creates_stock_client():
    import os

    with patch.dict(os.environ, {"ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "s"}):
        from tools.data import _data_client

        client = _data_client()
    assert client is not None


def test_crypto_client_creates_crypto_client():
    import os

    with patch.dict(os.environ, {"ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "s"}):
        from tools.data import _crypto_client

        client = _crypto_client()
    assert client is not None


def test_get_ohlcv_alpaca_key_error_falls_through_to_yfinance():
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame()

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch("tools.data._data_client") as mock_dc,
        patch("tools.data._is_crypto", return_value=False),
        patch("tools.data.api_call_span"),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        # Return empty dict so bar_list = [] → no result → yfinance fallback
        mock_dc.return_value.get_stock_bars.return_value = {}
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("SPY", "1Day", 5))

    assert result["bars"] == []


def test_get_ohlcv_yfinance_period_3mo():
    # bars=44 → days_needed=88 → yf_period="3mo"
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame()

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch("tools.data._data_client") as mock_dc,
        patch("tools.data._is_crypto", return_value=False),
        patch("tools.data.api_call_span"),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        mock_dc.return_value.get_stock_bars.return_value = {}
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("SPY", "1Day", 44))

    mock_yf.download.assert_called_once()
    assert mock_yf.download.call_args[1]["period"] == "3mo"
    assert result["bars"] == []


def test_get_ohlcv_yfinance_period_1y():
    # bars=200 → days_needed=400 → yf_period="1y"
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame()

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch("tools.data._data_client") as mock_dc,
        patch("tools.data._is_crypto", return_value=False),
        patch("tools.data.api_call_span"),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        mock_dc.return_value.get_stock_bars.return_value = {}
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("SPY", "1Day", 200))

    mock_yf.download.assert_called_once()
    assert mock_yf.download.call_args[1]["period"] == "1y"
    assert result["bars"] == []


def test_get_ohlcv_yfinance_flattens_multiindex_columns():
    # Simulate yf.download returning a MultiIndex DataFrame (common for single symbols)
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    cols = pd.MultiIndex.from_tuples(
        [("Open", "SPY"), ("High", "SPY"), ("Low", "SPY"), ("Close", "SPY"), ("Volume", "SPY")]
    )
    hist = pd.DataFrame(
        [[99.0, 101.0, 98.0, 100.0, 1e6], [100.0, 102.0, 99.0, 101.0, 1e6]],
        index=dates,
        columns=cols,
    )
    mock_yf = MagicMock()
    mock_yf.download.return_value = hist

    with (
        patch("infra.rate_limiter.acquire_alpaca_data", new_callable=AsyncMock),
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch("tools.data._data_client") as mock_dc,
        patch("tools.data._is_crypto", return_value=False),
        patch("tools.data.api_call_span"),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        mock_dc.return_value.get_stock_bars.return_value = {}
        from tools.data import get_ohlcv

        result = asyncio.run(get_ohlcv("SPY", "1Day", 2))

    assert len(result["bars"]) == 2
    assert result["bars"][0]["close"] == 100.0
