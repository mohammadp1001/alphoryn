"""Integration test: market regime detection from macro inputs (no API calls)."""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.parametrize(
    "vix, yield_10y, yield_2y, spy_return_20d, expected_regime",
    [
        (35.0, 4.5, 5.0, -5.0, "CRISIS"),
        (22.0, 4.0, 4.5, -1.0, "HIGH_VOL"),
        (12.0, 4.0, 3.8, 3.5, "BULL_TREND"),
        (14.0, 4.0, 3.9, -3.0, "BEAR_TREND"),
        (14.0, 4.0, 3.8, 0.5, "LOW_VOL_RANGE"),
    ],
)
def test_detect_market_regime_rules(
    vix: float,
    yield_10y: float,
    yield_2y: float,
    spy_return_20d: float,
    expected_regime: str,
) -> None:
    from tools.research.tools import detect_market_regime

    result = asyncio.run(detect_market_regime(vix, yield_10y, yield_2y, spy_return_20d))
    assert result["regime"] == expected_regime


def test_detect_market_regime_returns_reasoning() -> None:
    from tools.research.tools import detect_market_regime

    result = asyncio.run(detect_market_regime(35.0, 4.0, 4.5, -5.0, ))
    assert len(result["reasoning"]) > 10
    assert "yield_curve_spread" in result


def test_regime_enum_values_are_valid() -> None:
    """All returned regime values must be valid MarketRegime enum members."""
    from models.enums import MarketRegime
    from tools.research.tools import detect_market_regime

    for vix, y10, y2, spy in [(35, 4, 5, -5), (12, 4, 3.8, 3.5), (14, 4, 3.9, 0.5)]:
        result = asyncio.run(detect_market_regime(float(vix), float(y10), float(y2), float(spy)))
        MarketRegime(result["regime"])  # raises ValueError if invalid
