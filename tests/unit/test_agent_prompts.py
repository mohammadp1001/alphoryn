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


def test_risk_preamble_contains_output_fields():
    from agent.prompts import _RISK_PREAMBLE
    formatted = _RISK_PREAMBLE.format(calibration_summary="test")
    assert "recommended_level" in formatted
    assert "reasoning" in formatted
    assert "acknowledged_opposing_signal" in formatted


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


# ── New-content checks (prompt improvements) ─────────────────────────────────

def test_analysis_agent_has_pydantic_header():
    from agent.prompts import ANALYSIS_AGENT_INSTRUCTION
    assert "Pydantic model enforced" in ANALYSIS_AGENT_INSTRUCTION


def test_analysis_agent_has_score_formula():
    from agent.prompts import ANALYSIS_AGENT_INSTRUCTION
    assert "0.6" in ANALYSIS_AGENT_INSTRUCTION
    assert "0.4" in ANALYSIS_AGENT_INSTRUCTION
    assert "combined_score" in ANALYSIS_AGENT_INSTRUCTION


def test_analysis_agent_handles_empty_screen():
    from agent.prompts import ANALYSIS_AGENT_INSTRUCTION
    assert "zero symbols" in ANALYSIS_AGENT_INSTRUCTION or "empty list" in ANALYSIS_AGENT_INSTRUCTION


def test_research_agent_has_tool_sequence():
    from agent.prompts import RESEARCH_AGENT_INSTRUCTION
    assert "get_macro_data" in RESEARCH_AGENT_INSTRUCTION
    assert "detect_market_regime" in RESEARCH_AGENT_INSTRUCTION
    assert "get_sentiment" in RESEARCH_AGENT_INSTRUCTION


def test_research_agent_sentiment_derivation():
    from agent.prompts import RESEARCH_AGENT_INSTRUCTION
    assert "majority label" in RESEARCH_AGENT_INSTRUCTION


def test_research_agent_sector_tickers_not_names():
    from agent.prompts import RESEARCH_AGENT_INSTRUCTION
    assert '"XLK"' in RESEARCH_AGENT_INSTRUCTION
    assert "NOT" in RESEARCH_AGENT_INSTRUCTION


def test_risk_pessimist_reads_optimist_verdict():
    from agent.prompts import RISK_PESSIMIST_INSTRUCTION
    formatted = RISK_PESSIMIST_INSTRUCTION.format(calibration_summary="x")
    assert "optimist" in formatted.lower()
    assert "strongest argument" in formatted.lower()


def test_risk_preamble_has_regime_priors():
    from agent.prompts import _RISK_PREAMBLE
    text = _RISK_PREAMBLE.format(calibration_summary="")
    assert "CRISIS" in text
    assert "BULL_TREND" in text
    assert "LOW_VOL_RANGE" in text


def test_execution_agent_has_sizing_formula():
    from agent.prompts import EXECUTION_AGENT_INSTRUCTION
    assert "0.10" in EXECUTION_AGENT_INSTRUCTION
    assert "0.20" in EXECUTION_AGENT_INSTRUCTION


def test_execution_agent_handles_existing_position():
    from agent.prompts import EXECUTION_AGENT_INSTRUCTION
    assert "already_held" in EXECUTION_AGENT_INSTRUCTION


def test_execution_agent_handles_insufficient_funds():
    from agent.prompts import EXECUTION_AGENT_INSTRUCTION
    assert "insufficient_funds" in EXECUTION_AGENT_INSTRUCTION


def test_coordinator_has_risk_debate_template():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "Risk debate request template" in formatted


def test_coordinator_write_ahead_before_execute():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    write_pos = formatted.find("Write-ahead")
    execute_pos = formatted.find("Execute")
    assert write_pos < execute_pos, "Write-ahead must appear before Execute in the cycle flow"


def test_coordinator_hitl_for_high_risk_any_mode():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "any mode" in formatted


def test_coordinator_credentials_not_passed_in_message():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "environment variables" in formatted
