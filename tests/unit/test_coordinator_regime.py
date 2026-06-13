"""Unit tests for tools.coordinator.tools.detect_market_regime — self-contained implementation."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


def _mock_yf_module(vix: float, yield_10y_raw: float, yield_2y_raw: float, bench_return_pct: float):
    """Build a yfinance mock module for the given macro values."""
    mock_yf = MagicMock()

    # Map symbol → raw market price (^TNX / ^IRX quote in tenths)
    raw_prices = {"^VIX": vix, "^TNX": yield_10y_raw, "^IRX": yield_2y_raw}

    def _ticker(sym: str):
        t = MagicMock()
        price = raw_prices.get(sym, 0.0)
        t.info = MagicMock()
        t.info.get.side_effect = lambda key, default=None: (
            price if key == "regularMarketPrice" else default
        )
        return t

    mock_yf.Ticker.side_effect = _ticker

    base = 100.0
    end_val = base * (1 + bench_return_pct / 100)
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    # detect_market_regime does yf.download(...)["Close"] — return a DataFrame
    mock_yf.download.return_value = pd.DataFrame({"Close": [base, end_val]}, index=dates)

    return mock_yf


def _run_detect(vix, yield_10y_raw, yield_2y_raw, bench_ret, **kwargs):
    mock_yf = _mock_yf_module(vix, yield_10y_raw, yield_2y_raw, bench_ret)
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        # Force re-import to pick up the patched module
        import importlib

        import tools.coordinator.tools as coord_mod

        importlib.reload(coord_mod)
        return asyncio.run(coord_mod.detect_market_regime(**kwargs))


@pytest.mark.parametrize(
    "vix,yield_10y_raw,yield_2y_raw,bench_ret,expected_regime",
    [
        (35.0, 45.0, 50.0, -5.0, "CRISIS"),
        (22.0, 40.0, 45.0, -1.0, "HIGH_VOL"),
        (12.0, 40.0, 38.0, 3.5, "BULL_TREND"),
        (14.0, 40.0, 39.0, -3.0, "BEAR_TREND"),
        (14.0, 40.0, 38.0, 0.5, "LOW_VOL_RANGE"),
    ],
)
def test_detect_market_regime_rules(vix, yield_10y_raw, yield_2y_raw, bench_ret, expected_regime):
    result = _run_detect(vix, yield_10y_raw, yield_2y_raw, bench_ret)
    assert result["regime"] == expected_regime


def test_detect_market_regime_returns_all_fields():
    result = _run_detect(35.0, 45.0, 50.0, -5.0)
    for key in (
        "regime",
        "vix",
        "yield_10y",
        "yield_2y",
        "yield_curve_spread",
        "benchmark_symbol",
        "benchmark_return_20d",
        "reasoning",
    ):
        assert key in result


def test_detect_market_regime_yield_curve_spread():
    # yield_10y_raw=40 → 4.0%; yield_2y_raw=50 → 5.0%; spread = -1.0
    result = _run_detect(22.0, 40.0, 50.0, -1.0)
    assert abs(result["yield_curve_spread"] - (-1.0)) < 0.01


def test_detect_market_regime_reasoning_not_empty():
    result = _run_detect(12.0, 40.0, 38.0, 3.5)
    assert len(result["reasoning"]) > 10


def test_detect_market_regime_benchmark_exception_returns_zero_return():
    mock_yf = MagicMock()
    mock_info = MagicMock()
    mock_info.get.side_effect = lambda key, default=None: (
        25.0 if key == "regularMarketPrice" else default
    )
    mock_yf.Ticker.return_value = MagicMock(info=mock_info)
    mock_yf.download.side_effect = Exception("network error")

    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        import importlib

        import tools.coordinator.tools as coord_mod

        importlib.reload(coord_mod)
        result = asyncio.run(coord_mod.detect_market_regime())

    assert result["benchmark_return_20d"] == 0.0
    assert result["regime"] == "HIGH_VOL"


def test_detect_market_regime_custom_benchmark():
    result = _run_detect(12.0, 40.0, 38.0, 3.5, benchmark_symbol="EWG")
    assert result["benchmark_symbol"] == "EWG"


def test_detect_market_regime_regime_enum_valid():
    from models.enums import MarketRegime

    result = _run_detect(12.0, 40.0, 38.0, 3.5)
    MarketRegime(result["regime"])  # raises ValueError if invalid
