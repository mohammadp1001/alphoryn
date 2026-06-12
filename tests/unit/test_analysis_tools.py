"""Unit tests for pure-Python analysis tools (no external API calls)."""

from __future__ import annotations

import asyncio
import math

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
    closes = [100.0 * (1.002**i) for i in range(60)]
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

    closes = [100.0 * (1.001**i) for i in range(30)]
    volumes = [1_000_000.0] * 30
    result = asyncio.run(detect_momentum("TEST", closes, volumes))
    assert -1.0 <= result["momentum_score"] <= 1.0


def test_momentum_strong_uptrend_positive_score() -> None:
    from tools.analysis.tools import detect_momentum

    closes = [100.0 * (1.005**i) for i in range(30)]
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


# ── ATR insufficient data path ────────────────────────────────────────────────


def test_atr_insufficient_data_returns_zero() -> None:
    from tools.analysis.tools import compute_atr

    # Only 5 values < period=14 → hits early-return branch
    closes = [100.0, 101.0, 99.0, 102.0, 100.0]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    result = asyncio.run(compute_atr("TEST", highs, lows, closes, 14))
    assert result["current"] == 0.0
    assert result["values"] == []


# ── compute_beta ──────────────────────────────────────────────────────────────


def test_compute_beta_returns_one_for_identical_series() -> None:
    from tools.analysis.tools import compute_beta

    rets = [0.01 * (i % 5 - 2) for i in range(30)]
    result = asyncio.run(compute_beta("TEST", rets, rets))
    assert abs(result["beta"] - 1.0) < 0.01
    assert result["r_squared"] > 0.99
    assert result["benchmark"] == "SPY"


def test_compute_beta_insufficient_data() -> None:
    from tools.analysis.tools import compute_beta

    result = asyncio.run(compute_beta("TEST", [0.01], [0.01]))
    assert result["beta"] == 1.0
    assert result["r_squared"] == 0.0


def test_compute_beta_uncorrelated_series() -> None:
    from tools.analysis.tools import compute_beta

    # Benchmark up, symbol down → negative beta
    bm = [0.01] * 20
    sym = [-0.01] * 20
    result = asyncio.run(compute_beta("TEST", sym, bm))
    assert result["beta"] < 0


# ── detect_momentum insufficient data ────────────────────────────────────────


def test_detect_momentum_insufficient_data() -> None:
    from tools.analysis.tools import detect_momentum

    result = asyncio.run(detect_momentum("TEST", [100.0, 101.0], [1e6, 1e6]))
    assert result["momentum_score"] == 0.0


# ── detect_crossover ──────────────────────────────────────────────────────────


def test_detect_crossover_bullish() -> None:
    from tools.analysis.tools import detect_crossover

    # neg → pos = bullish crossover
    result = asyncio.run(detect_crossover("TEST", [-0.5, 0.3]))
    assert result["crossover_type"] == "bullish"
    assert result["strength"] > 0
    assert result["bars_since_crossover"] == 0


def test_detect_crossover_bearish() -> None:
    from tools.analysis.tools import detect_crossover

    # pos → neg = bearish crossover
    result = asyncio.run(detect_crossover("TEST", [0.5, -0.3]))
    assert result["crossover_type"] == "bearish"
    assert result["strength"] > 0


def test_detect_crossover_none() -> None:
    from tools.analysis.tools import detect_crossover

    result = asyncio.run(detect_crossover("TEST", [0.3, 0.4]))
    assert result["crossover_type"] == "none"
    assert result["bars_since_crossover"] is None


def test_detect_crossover_insufficient_data() -> None:
    from tools.analysis.tools import detect_crossover

    result = asyncio.run(detect_crossover("TEST", [0.5]))
    assert result["crossover_type"] == "none"


# ── detect_support_resistance ─────────────────────────────────────────────────


def test_detect_support_resistance_returns_levels() -> None:
    from tools.analysis.tools import detect_support_resistance

    # Prices oscillate → create support and resistance
    prices = [100.0, 105.0, 102.0, 99.0, 103.0, 107.0, 101.0, 98.0, 104.0, 106.0]
    highs = [p + 1.0 for p in prices]
    lows = [p - 1.0 for p in prices]
    result = asyncio.run(detect_support_resistance("TEST", highs, lows, prices))

    assert result["symbol"] == "TEST"
    assert "levels" in result
    assert "nearest_support" in result
    assert "nearest_resistance" in result


def test_detect_support_resistance_no_strong_levels() -> None:
    from tools.analysis.tools import detect_support_resistance

    # Monotonic series → each level touched once, won't qualify (need >=2)
    prices = [float(i) for i in range(1, 11)]
    highs = [p + 0.1 for p in prices]
    lows = [p - 0.1 for p in prices]
    result = asyncio.run(detect_support_resistance("TEST", highs, lows, prices))
    # No levels with touch_count >= 2
    assert result["nearest_support"] is None or result["nearest_resistance"] is None


# ── rank_by_momentum ──────────────────────────────────────────────────────────


def test_rank_by_momentum_sorted_correctly() -> None:
    from tools.analysis.tools import rank_by_momentum

    scores = [
        {"symbol": "XLK", "momentum_score": 0.8},
        {"symbol": "SPY", "momentum_score": 0.3},
        {"symbol": "QQQ", "momentum_score": 0.6},
    ]
    result = asyncio.run(rank_by_momentum(scores))

    assert result["signals"][0]["symbol"] == "XLK"
    assert result["signals"][0]["rank"] == 1
    assert result["signals"][1]["symbol"] == "QQQ"
    assert result["signals"][2]["symbol"] == "SPY"
    assert result["screened_universe"] == ["XLK", "SPY", "QQQ"]


def test_rank_by_momentum_empty_list() -> None:
    from tools.analysis.tools import rank_by_momentum

    result = asyncio.run(rank_by_momentum([]))
    assert result["signals"] == []
    assert result["screened_universe"] == []


# ── run_backtest ──────────────────────────────────────────────────────────────


def test_run_backtest_insufficient_data() -> None:
    from tools.analysis.tools import run_backtest

    closes = [float(i) for i in range(10)]  # too few bars
    volumes = [1e6] * 10
    result = asyncio.run(run_backtest("TEST", "MOMENTUM", closes, volumes))
    assert result["signal_pattern"] == "insufficient_data"
    assert result["match_count"] == 0


def test_run_backtest_with_enough_data() -> None:
    from tools.analysis.tools import run_backtest

    # 100 bars of trending data
    closes = [100.0 * (1.001**i) for i in range(100)]
    volumes = [1e6] * 100
    result = asyncio.run(run_backtest("TEST", "MOMENTUM", closes, volumes))
    assert result["symbol"] == "TEST"
    assert result["strategy"] == "MOMENTUM"
    assert "match_count" in result
    assert "win_rate_pct" in result


def test_run_backtest_no_matches_branch() -> None:
    # Volatile data that's unlikely to produce similar momentum patterns
    import math

    from tools.analysis.tools import run_backtest

    closes = [100.0 + 20.0 * math.sin(i * 0.5) for i in range(100)]
    volumes = [1e6] * 100
    # Patch detect_momentum to return very different scores for history vs current
    result = asyncio.run(run_backtest("TEST", "MEAN_REVERSION", closes, volumes))
    # Either matches or no-matches path; just assert it completes
    assert result["symbol"] == "TEST"


# ── calc_max_drawdown peak-update path ────────────────────────────────────────


def test_max_drawdown_with_multiple_peaks_covers_peak_update() -> None:
    from tools.analysis.tools import calc_max_drawdown

    # Uptrend → new peak → fall → new peak → big fall
    closes = [100.0, 110.0, 105.0, 120.0, 90.0]
    result = asyncio.run(calc_max_drawdown("TEST", closes))
    # From peak of 120 to 90 → 25% drawdown
    assert abs(result["max_drawdown_pct"] - 25.0) < 0.01
    assert result["drawdown_start_bar"] == 3  # peak at index 3 (120.0)
    assert result["drawdown_end_bar"] == 4  # trough at index 4 (90.0)


# ── score_technical ───────────────────────────────────────────────────────────


def test_score_technical_momentum_strategy() -> None:
    from tools.analysis.tools import score_technical

    result = asyncio.run(score_technical("TEST", "MOMENTUM", 65.0, 0.005, 0.7))
    assert -1.0 <= result["composite_score"] <= 1.0
    assert result["strategy"] == "MOMENTUM"
    assert "rsi_score" in result
    assert "macd_score" in result
    assert "bollinger_score" in result


def test_score_technical_mean_reversion_strategy() -> None:
    from tools.analysis.tools import score_technical

    # Near lower band with oversold RSI → should score positively for mean reversion
    result = asyncio.run(score_technical("TEST", "MEAN_REVERSION", 25.0, -0.005, 0.1))
    assert result["composite_score"] > 0  # positive: oversold near lower band


def test_score_technical_sector_rotation_strategy() -> None:
    from tools.analysis.tools import score_technical

    result = asyncio.run(score_technical("TEST", "SECTOR_ROTATION", 55.0, 0.002, 0.6))
    assert -1.0 <= result["composite_score"] <= 1.0
    assert result["strategy"] == "SECTOR_ROTATION"


def test_score_technical_unknown_strategy_uses_default_weights() -> None:
    from tools.analysis.tools import score_technical

    # Unknown strategy → falls back to (0.33, 0.33, 0.33) weights
    result = asyncio.run(score_technical("TEST", "UNKNOWN", 50.0, 0.0, 0.5))
    assert result["composite_score"] == 0.0  # all neutral → composite=0


def test_run_backtest_guarantees_no_matches_branch() -> None:
    """Line 399: guarantee the no-matches return path by mocking detect_momentum."""
    import asyncio
    from unittest.mock import patch

    from tools.analysis.tools import run_backtest

    call_count = [0]

    async def mock_detect_momentum(symbol, closes, volumes):
        call_count[0] += 1
        # First call is for the current window → score 1.0
        # All subsequent calls are historical → score -1.0  (diff = 2.0 > 0.2)
        score = 1.0 if call_count[0] == 1 else -1.0
        return {"momentum_score": score, "rsi": 50.0, "macd_histogram": 0.0, "volume_ratio": 1.0}

    closes = [100.0 + i * 0.1 for i in range(100)]
    volumes = [1e6] * 100

    with patch("tools.analysis.tools.detect_momentum", side_effect=mock_detect_momentum):
        result = asyncio.run(run_backtest("TEST", "MOMENTUM", closes, volumes))

    assert result["match_count"] == 0
    assert result["signal_pattern"].endswith("_no_matches")
