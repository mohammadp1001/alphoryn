"""Unit tests for agent.prompts — all prompt templates must be valid Python format strings."""
from __future__ import annotations

import pytest


# ── Import all prompts ────────────────────────────────────────────────────────

def test_research_agent_instruction_is_string():
    from agent.prompts import RESEARCH_AGENT_INSTRUCTION
    assert isinstance(RESEARCH_AGENT_INSTRUCTION, str)
    assert len(RESEARCH_AGENT_INSTRUCTION) > 0


def test_analysis_agent_instruction_is_string():
    from agent.prompts import ANALYSIS_AGENT_INSTRUCTION
    assert isinstance(ANALYSIS_AGENT_INSTRUCTION, str)
    assert len(ANALYSIS_AGENT_INSTRUCTION) > 0


def test_execution_agent_instruction_is_string():
    from agent.prompts import EXECUTION_AGENT_INSTRUCTION
    assert isinstance(EXECUTION_AGENT_INSTRUCTION, str)
    assert len(EXECUTION_AGENT_INSTRUCTION) > 0


# ── _RISK_PREAMBLE format ─────────────────────────────────────────────────────

def test_risk_preamble_formats_without_key_error():
    """The JSON block inside _RISK_PREAMBLE uses {{ }} — must not raise KeyError."""
    from agent.prompts import _RISK_PREAMBLE
    # Should not raise a KeyError on the JSON example block
    formatted = _RISK_PREAMBLE.format(calibration_summary="No data yet.")
    assert "No data yet." in formatted


def test_risk_preamble_contains_verdict_tag():
    from agent.prompts import _RISK_PREAMBLE
    formatted = _RISK_PREAMBLE.format(calibration_summary="test")
    assert "VERDICT" in formatted


def test_risk_optimist_instruction_formats_correctly():
    from agent.prompts import RISK_OPTIMIST_INSTRUCTION
    formatted = RISK_OPTIMIST_INSTRUCTION.format(calibration_summary="opt context")
    assert "opt context" in formatted
    assert "OPTIMIST" in formatted


def test_risk_pessimist_instruction_formats_correctly():
    from agent.prompts import RISK_PESSIMIST_INSTRUCTION
    formatted = RISK_PESSIMIST_INSTRUCTION.format(calibration_summary="pess context")
    assert "pess context" in formatted
    assert "PESSIMIST" in formatted


def test_risk_optimist_contains_recommended_level_in_json_block():
    from agent.prompts import RISK_OPTIMIST_INSTRUCTION
    formatted = RISK_OPTIMIST_INSTRUCTION.format(calibration_summary="x")
    assert "recommended_level" in formatted


def test_risk_pessimist_contains_recommended_level_in_json_block():
    from agent.prompts import RISK_PESSIMIST_INSTRUCTION
    formatted = RISK_PESSIMIST_INSTRUCTION.format(calibration_summary="x")
    assert "recommended_level" in formatted


# ── COORDINATOR_INSTRUCTION format ────────────────────────────────────────────

_COORD_BASE_KWARGS = dict(
    session_id="test-session-id",
    strategy="MOMENTUM",
    mode="SEMI_AUTO",
    loss_limit_eur=500.0,
    shortlist_n=2,
    hitl_timeout_seconds=60,
    hitl_timeout_action="abort",
    universe="US_SECTOR_ETFS",
    symbols="XLK, XLE, XLF",
)


def test_coordinator_instruction_formats_without_error():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "test-session-id" in formatted
    assert "MOMENTUM" in formatted
    assert "SEMI_AUTO" in formatted
    assert "500.0" in formatted
    assert "US_SECTOR_ETFS" in formatted
    assert "XLK" in formatted


def test_coordinator_instruction_all_strategies():
    from agent.prompts import COORDINATOR_INSTRUCTION
    for strategy in ["MOMENTUM", "MEAN_REVERSION", "SECTOR_ROTATION"]:
        formatted = COORDINATOR_INSTRUCTION.format(**{**_COORD_BASE_KWARGS, "strategy": strategy})
        assert strategy in formatted


def test_coordinator_instruction_all_modes():
    from agent.prompts import COORDINATOR_INSTRUCTION
    for mode in ["SEMI_AUTO", "FULL_AUTO"]:
        formatted = COORDINATOR_INSTRUCTION.format(**{**_COORD_BASE_KWARGS, "mode": mode})
        assert mode in formatted


def test_coordinator_instruction_mentions_decision_cycle_flow():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "research" in formatted.lower()
    assert "execution" in formatted.lower()


# ── Risk prompts mention key rules ────────────────────────────────────────────

def test_risk_preamble_mentions_asymmetric_debate():
    from agent.prompts import _RISK_PREAMBLE
    text = _RISK_PREAMBLE.format(calibration_summary="")
    assert "HIGH risk" in text or "MEDIUM" in text or "LOW" in text


def test_execution_agent_mentions_paper_account():
    from agent.prompts import EXECUTION_AGENT_INSTRUCTION
    assert "PAPER" in EXECUTION_AGENT_INSTRUCTION or "paper" in EXECUTION_AGENT_INSTRUCTION.lower()


def test_execution_agent_mentions_credentials_security():
    from agent.prompts import EXECUTION_AGENT_INSTRUCTION
    assert "credentials" in EXECUTION_AGENT_INSTRUCTION.lower() or "api keys" in EXECUTION_AGENT_INSTRUCTION.lower()
