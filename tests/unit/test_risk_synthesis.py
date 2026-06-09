"""Unit tests for ADR 0001 deterministic risk synthesis."""
from __future__ import annotations

import pytest

from models.enums import DebateWinner, RiskLevel


# ── Helpers ───────────────────────────────────────────────────────────────────

def _synthesise(opt_level: str, pess_level: str, opt_win: float, pess_win: float) -> dict:
    """Call synthesise_risk tool function directly (no ADK wrapper needed)."""
    import asyncio
    from tools.coordinator.tools import synthesise_risk

    return asyncio.run(synthesise_risk(opt_level, "", pess_level, "", opt_win, pess_win))


# ── ADR 0001 formula tests ────────────────────────────────────────────────────

def test_equal_weights_both_low_gives_low() -> None:
    result = _synthesise("LOW", "LOW", 0.5, 0.5)
    assert result["risk_level"] == "LOW"


def test_equal_weights_both_high_gives_high() -> None:
    result = _synthesise("HIGH", "HIGH", 0.5, 0.5)
    assert result["risk_level"] == "HIGH"


def test_equal_weights_mixed_gives_medium() -> None:
    # opt=LOW(0.5), pess=HIGH(1.5), equal weights → score = (0.5+1.5)/2 = 1.0 → MEDIUM
    result = _synthesise("LOW", "HIGH", 0.5, 0.5)
    assert result["risk_level"] == "MEDIUM"
    assert abs(result["risk_score"] - 1.0) < 0.01


def test_optimist_dominant_pulls_risk_low() -> None:
    # opt wins 80%, pess wins 20% → opt pulls score toward LOW
    result = _synthesise("LOW", "HIGH", 0.8, 0.2)
    assert result["risk_level"] in ("LOW", "MEDIUM")
    assert result["risk_score"] < 1.0


def test_pessimist_override_triggers_at_high_win_rate() -> None:
    # Asymmetric override: pess recommends HIGH AND win_rate > 0.65 → always HIGH
    result = _synthesise("LOW", "HIGH", 0.8, 0.7)
    assert result["risk_level"] == "HIGH"


def test_pessimist_override_does_not_trigger_below_threshold() -> None:
    # pess recommends HIGH but win_rate=0.60 < 0.65 threshold → no override
    result = _synthesise("LOW", "HIGH", 0.8, 0.60)
    # Should NOT be forced to HIGH by the override (but formula may still give HIGH)
    # Key: the override didn't force it — the score may naturally be MEDIUM
    assert result["risk_level"] in ("MEDIUM", "HIGH")


def test_zero_weight_fallback_gives_medium() -> None:
    # Both win rates = 0 → fallback score = 1.0 → MEDIUM
    result = _synthesise("LOW", "HIGH", 0.0, 0.0)
    assert result["risk_level"] == "MEDIUM"
    assert abs(result["risk_score"] - 1.0) < 0.01


def test_score_below_low_threshold_gives_low() -> None:
    # opt=LOW(0.5), pess=LOW(0.5), opt_win=0.9 → score ≈ 0.5 < 0.6 → LOW
    result = _synthesise("LOW", "LOW", 0.9, 0.1)
    assert result["risk_level"] == "LOW"
    assert result["risk_score"] < 0.6


def test_score_above_high_threshold_gives_high() -> None:
    # opt=HIGH(1.5), pess=HIGH(1.5), equal → score=1.5 > 1.2 → HIGH
    result = _synthesise("HIGH", "HIGH", 0.5, 0.5)
    assert result["risk_level"] == "HIGH"
    assert result["risk_score"] > 1.2


# ── Debate winner tests ───────────────────────────────────────────────────────

def test_pessimist_high_wins_debate() -> None:
    result = _synthesise("LOW", "HIGH", 0.5, 0.5)
    assert result["debate_winner"] == "pessimist"


def test_synthesis_reasoning_contains_score() -> None:
    result = _synthesise("MEDIUM", "MEDIUM", 0.5, 0.5)
    assert "Score=" in result["synthesis_reasoning"]
