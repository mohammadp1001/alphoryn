"""Unit tests for pure-Python analysis tools (no external API calls)."""
from __future__ import annotations

import asyncio
import math

import pytest


# ── RSI ───────────────────────────────────────────────────────────────────────

def test_rsi_overbought() -> None:
    from tools.analysis.tools import compute_rsi

    # Monotonically rising prices → RSI near 100
    closes = [float(i) for i in range(1, 52)]
    result = asyncio.run(compute_rsi("TEST", closes, 14))
    assert result["is_overbought"]
    assert result["current"] > 70


def test_rsi_oversold() -> None:
    from tools.analysis.tools import compute_rsi

    # Monotonically falling prices → RSI near 0
    closes = [float(100 - i) for i in range(51)]
    result = asyncio.run(compute_rsi("TEST", closes, 14))
    assert result["is_oversold"]
    assert result["current"] < 30


def test_rsi_neutral_range() -> None:
    from tools.analysis.tools import compute_rsi

    # Alternating prices → RSI near 50
    closes = [100.0 + (1 if i % 2 == 0 else -1) for i in range(30)]
    result = asyncio.run(compute_rsi("TEST", closes, 14))
    assert 30 <= result["current"] <= 70


def test_rsi_insufficient_data_returns_50() -> None:
    from tools.analysis.tools import compute_rsi

    result = asyncio.run(compute_rsi("TEST", [100.0, 101.0], 14))
    assert result["current"] == 50.0
    assert result["values"] == []


# ── MACD ──────────────────────────────────────────────────────────────────────

def test_macd_returns_required_keys() -> None:
    from tools.analysis.tools import compute_macd

    closes = [100.0 + math.sin(i * 0.2) * 5 for i in range(60)]
    result = asyncio.run(compute_macd("TEST", closes))
    assert all(k in result for k in ("current_macd", "current_signal", "current_histogram"))


def test_macd_bull_trend_positive_histogram() -> None:
    from tools.analysis.tools import compute_macd

    # Strong uptrend → MACD histogram should be positive
    closes = [100.0 * (1.002 ** i) for i in range(60)]
    result = asyncio.run(compute_macd("TEST", closes))
    assert result["current_histogram"] > 0


# ── Bollinger Bands ───────────────────────────────────────────────────────────

def test_bollinger_price_inside_bands() -> None:
    from tools.analysis.tools import compute_bollinger

    closes = [100.0 + math.sin(i * 0.3) * 2 for i in range(30)]
    result = asyncio.run(compute_bollinger("TEST", closes, 20))
    assert result["current_lower"] < result["current_price"] < result["current_upper"]


def test_bollinger_bandwidth_positive() -> None:
    from tools.analysis.tools import compute_bollinger

    closes = [100.0 + (i % 5) for i in range(25)]
    result = asyncio.run(compute_bollinger("TEST", closes, 20))
    assert result["bandwidth"] > 0
    assert 0.0 <= result["pct_b"] <= 2.0  # may exceed [0,1] for extreme prices


# ── ATR ───────────────────────────────────────────────────────────────────────

def test_atr_positive_for_volatile_data() -> None:
    from tools.analysis.tools import compute_atr

    n = 20
    closes = [100.0 + i for i in range(n)]
    highs = [c + 2.0 for c in closes]
    lows = [c - 2.0 for c in closes]
    result = asyncio.run(compute_atr("TEST", highs, lows, closes, 14))
    assert result["current"] > 0


# ── Momentum ─────────────────────────────────────────────────────────────────

def test_momentum_score_in_range() -> None:
    from tools.analysis.tools import detect_momentum

    closes = [100.0 * (1.001 ** i) for i in range(30)]
    volumes = [1_000_000.0] * 30
    result = asyncio.run(detect_momentum("TEST", closes, volumes))
    assert -1.0 <= result["momentum_score"] <= 1.0


def test_momentum_strong_uptrend_positive_score() -> None:
    from tools.analysis.tools import detect_momentum

    closes = [100.0 * (1.005 ** i) for i in range(30)]
    volumes = [1_500_000.0] * 30
    result = asyncio.run(detect_momentum("TEST", closes, volumes))
    assert result["momentum_score"] > 0


# ── Drawdown ─────────────────────────────────────────────────────────────────

def test_max_drawdown_flat_series_zero() -> None:
    from tools.analysis.tools import calc_max_drawdown

    result = asyncio.run(calc_max_drawdown("TEST", [100.0] * 20))
    assert result["max_drawdown_pct"] == 0.0


def test_max_drawdown_known_value() -> None:
    from tools.analysis.tools import calc_max_drawdown

    # 100 → 80 → 90 → 70 → max drawdown from 100 to 70 = 30%
    closes = [100.0, 90.0, 80.0, 85.0, 70.0]
    result = asyncio.run(calc_max_drawdown("TEST", closes))
    assert abs(result["max_drawdown_pct"] - 30.0) < 0.01


# ── Correlation ──────────────────────────────────────────────────────────────

def test_correlation_perfect_positive() -> None:
    from tools.analysis.tools import calc_correlation

    a = [float(i) for i in range(10)]
    result = asyncio.run(calc_correlation(["A", "B"], [a, a]))
    assert abs(result["matrix"][0][1] - 1.0) < 0.001


def test_correlation_perfect_negative() -> None:
    from tools.analysis.tools import calc_correlation

    a = [float(i) for i in range(10)]
    b = [float(9 - i) for i in range(10)]
    result = asyncio.run(calc_correlation(["A", "B"], [a, b]))
    assert abs(result["matrix"][0][1] + 1.0) < 0.001


# ── Sharpe ────────────────────────────────────────────────────────────────────

def test_sharpe_zero_volatility_returns_zero() -> None:
    from tools.analysis.tools import calc_sharpe

    result = asyncio.run(calc_sharpe("TEST", [0.1] * 30))
    # All identical returns → std=0 → sharpe=0
    assert result["sharpe_ratio"] == 0.0
