"""Unit tests for models.risk — RiskAssessment.synthesise and supporting models."""
from __future__ import annotations

import pytest

from models.enums import RiskLevel, Strategy, MarketRegime
from models.risk import (
    AgentCalibration,
    AgentVerdict,
    CandidateShortlist,
    RiskAssessment,
)


# ── AgentVerdict ──────────────────────────────────────────────────────────────

def test_agent_verdict_creation():
    verdict = AgentVerdict(
        agent="optimist",
        recommended_level=RiskLevel.LOW,
        reasoning="Strong momentum signals.",
        acknowledged_opposing_signal="VIX elevated slightly",
    )
    assert verdict.agent == "optimist"
    assert verdict.recommended_level == RiskLevel.LOW


def test_agent_verdict_high_risk():
    verdict = AgentVerdict(
        agent="pessimist",
        recommended_level=RiskLevel.HIGH,
        reasoning="Overbought and yield inversion.",
        acknowledged_opposing_signal="MACD bullish crossover",
    )
    assert verdict.recommended_level == RiskLevel.HIGH


# ── AgentCalibration ──────────────────────────────────────────────────────────

def test_agent_calibration_has_data_true():
    cal = AgentCalibration(
        agent="optimist",
        market_regime=MarketRegime.BULL_TREND,
        strategy=Strategy.MOMENTUM,
        wins=7,
        losses=3,
        ties=0,
        win_rate=0.7,
        has_data=True,
    )
    assert cal.has_data is True
    assert cal.win_rate == 0.7


def test_agent_calibration_cold_start():
    cal = AgentCalibration(
        agent="pessimist",
        market_regime=MarketRegime.BEAR_TREND,
        strategy=Strategy.MEAN_REVERSION,
        wins=0,
        losses=0,
        ties=0,
        win_rate=0.5,
        has_data=False,
    )
    assert cal.has_data is False
    assert cal.win_rate == 0.5


# ── RiskAssessment.synthesise ─────────────────────────────────────────────────

def _make_verdict(agent: str, level: RiskLevel) -> AgentVerdict:
    return AgentVerdict(
        agent=agent,
        recommended_level=level,
        reasoning="Test reasoning",
        acknowledged_opposing_signal="Signal X",
    )


def test_synthesise_both_low_gives_low():
    opt = _make_verdict("optimist", RiskLevel.LOW)
    pess = _make_verdict("pessimist", RiskLevel.LOW)
    result = RiskAssessment.synthesise(opt, pess, 0.5, 0.5, "test")
    assert result.level == RiskLevel.LOW


def test_synthesise_both_high_gives_high():
    opt = _make_verdict("optimist", RiskLevel.HIGH)
    pess = _make_verdict("pessimist", RiskLevel.HIGH)
    result = RiskAssessment.synthesise(opt, pess, 0.5, 0.5, "test")
    assert result.level == RiskLevel.HIGH


def test_synthesise_mixed_gives_medium():
    opt = _make_verdict("optimist", RiskLevel.LOW)
    pess = _make_verdict("pessimist", RiskLevel.HIGH)
    result = RiskAssessment.synthesise(opt, pess, 0.5, 0.5, "test")
    assert result.level == RiskLevel.MEDIUM


def test_synthesise_zero_weights_fallback():
    opt = _make_verdict("optimist", RiskLevel.LOW)
    pess = _make_verdict("pessimist", RiskLevel.HIGH)
    # Both zero → fallback to equal weight 0.5/0.5
    result = RiskAssessment.synthesise(opt, pess, 0.0, 0.0, "test")
    assert result.level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)
    assert result.weighted_score >= 0


def test_synthesise_pessimist_override_triggers():
    opt = _make_verdict("optimist", RiskLevel.LOW)
    pess = _make_verdict("pessimist", RiskLevel.HIGH)
    # pess_win_rate > PESSIMIST_OVERRIDE_WIN_RATE (0.65) → override
    result = RiskAssessment.synthesise(opt, pess, 0.8, 0.7, "test")
    assert result.level == RiskLevel.HIGH
    assert result.override_applied is True


def test_synthesise_pessimist_override_not_triggered_below_threshold():
    opt = _make_verdict("optimist", RiskLevel.LOW)
    pess = _make_verdict("pessimist", RiskLevel.HIGH)
    # pess_win_rate = 0.60 < 0.65 threshold → no override
    result = RiskAssessment.synthesise(opt, pess, 0.8, 0.60, "test")
    assert result.override_applied is False


def test_synthesise_result_has_all_fields():
    opt = _make_verdict("optimist", RiskLevel.MEDIUM)
    pess = _make_verdict("pessimist", RiskLevel.MEDIUM)
    result = RiskAssessment.synthesise(opt, pess, 0.5, 0.5, "synthesis text")

    assert result.optimist_verdict is opt
    assert result.pessimist_verdict is pess
    assert result.synthesis_reasoning == "synthesis text"
    assert isinstance(result.weighted_score, float)
    assert result.level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)


def test_synthesise_score_above_high_threshold_gives_high():
    # Both HIGH → score > 1.2 → HIGH
    opt = _make_verdict("optimist", RiskLevel.HIGH)
    pess = _make_verdict("pessimist", RiskLevel.HIGH)
    result = RiskAssessment.synthesise(opt, pess, 0.5, 0.5, "test")
    assert result.level == RiskLevel.HIGH
    assert result.weighted_score > 1.2


def test_synthesise_score_below_low_threshold_gives_low():
    # Both LOW with optimist dominant → score < 0.6 → LOW
    opt = _make_verdict("optimist", RiskLevel.LOW)
    pess = _make_verdict("pessimist", RiskLevel.LOW)
    result = RiskAssessment.synthesise(opt, pess, 0.9, 0.1, "test")
    assert result.level == RiskLevel.LOW
    assert result.weighted_score < 0.6
