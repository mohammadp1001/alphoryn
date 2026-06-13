"""Unit tests for tools.fundamentals — get_etf_metrics, get_fund_flows, get_sector_performance."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

# ── get_etf_metrics ───────────────────────────────────────────────────────────


def test_get_etf_metrics_returns_expected_keys():
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = {
        "totalAssets": 10_000_000,
        "annualReportExpenseRatio": 0.0035,
        "navPrice": 450.0,
        "sharesOutstanding": 22_000_000,
    }
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_etf_metrics

        result = asyncio.run(get_etf_metrics("SPY"))

    assert result["symbol"] == "SPY"
    assert result["aum_usd"] == 10_000_000.0
    assert result["expense_ratio"] == 0.0035
    assert result["nav"] == 450.0
    assert result["shares_outstanding"] == 22_000_000.0


def test_get_etf_metrics_none_fields_default_to_zero():
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = {}
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_etf_metrics

        result = asyncio.run(get_etf_metrics("XLK"))

    assert result["aum_usd"] == 0.0
    assert result["expense_ratio"] == 0.0


# ── get_fund_flows ────────────────────────────────────────────────────────────


def test_get_fund_flows_inflow():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    hist = pd.DataFrame({"Close": [100.0, 101.0, 102.0], "Volume": [1e6, 1e6, 1e6]}, index=dates)
    mock_yf = MagicMock()
    mock_yf.download.return_value = hist
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_fund_flows

        result = asyncio.run(get_fund_flows("SPY"))

    assert result["flow_direction"] == "inflow"
    assert result["estimated_flow_usd"] > 0


def test_get_fund_flows_outflow():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    hist = pd.DataFrame({"Close": [102.0, 101.0, 100.0], "Volume": [1e6, 1e6, 1e6]}, index=dates)
    mock_yf = MagicMock()
    mock_yf.download.return_value = hist
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_fund_flows

        result = asyncio.run(get_fund_flows("SPY"))

    assert result["flow_direction"] == "outflow"


def test_get_fund_flows_empty_hist_returns_neutral():
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame()
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_fund_flows

        result = asyncio.run(get_fund_flows("SPY"))

    assert result["flow_direction"] == "neutral"
    assert result["estimated_flow_usd"] == 0.0


def test_get_fund_flows_single_row_returns_neutral():
    dates = pd.date_range("2026-01-01", periods=1, freq="D")
    hist = pd.DataFrame({"Close": [100.0], "Volume": [1e6]}, index=dates)
    mock_yf = MagicMock()
    mock_yf.download.return_value = hist
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_fund_flows

        result = asyncio.run(get_fund_flows("SPY"))

    assert result["flow_direction"] == "neutral"


# ── get_sector_performance ────────────────────────────────────────────────────


def test_get_sector_performance_default_symbols():
    # Uses hardcoded sector map (no Ticker call) — download returns a DataFrame
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame({"Close": [100.0, 105.0]}, index=dates)
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_sector_performance

        result = asyncio.run(get_sector_performance("1mo"))

    assert "returns" in result
    assert result["timeframe"] == "1mo"
    # At least one symbol should have succeeded
    assert len(result["returns"]) >= 1


def test_get_sector_performance_custom_symbols():
    # Custom symbols path: sector_map={} → Ticker().info.get("sector")
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame({"Close": [100.0, 110.0]}, index=dates)
    mock_yf.Ticker.return_value.info = {"sector": "Technology"}
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_sector_performance

        result = asyncio.run(get_sector_performance("1mo", symbols=["XLK"]))

    assert len(result["returns"]) == 1
    assert result["returns"][0]["symbol"] == "XLK"
    assert result["returns"][0]["return_pct"] == 10.0


def test_get_sector_performance_exception_skips_symbol():
    mock_yf = MagicMock()
    mock_yf.download.side_effect = Exception("API error")
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_sector_performance

        result = asyncio.run(get_sector_performance("1mo", symbols=["BAD"]))

    assert result["returns"] == []


def test_get_sector_performance_sector_lookup_exception_uses_unknown():
    # Ticker().info.get raises so sector falls back to "Unknown"
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame({"Close": [100.0, 103.0]}, index=dates)
    mock_info = MagicMock()
    mock_info.get.side_effect = Exception("yf error")
    mock_yf.Ticker.return_value.info = mock_info
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.fundamentals import get_sector_performance

        result = asyncio.run(get_sector_performance("1mo", symbols=["EWG"]))

    assert result["returns"][0]["sector"] == "Unknown"
