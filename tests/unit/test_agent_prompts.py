"""Unit tests for agent.prompts — all prompt templates must be valid Python format strings."""
from __future__ import annotations

import pytest


# ── Risk preamble ─────────────────────────────────────────────────────────────

def test_risk_preamble_formats_without_key_error():
    from agent.prompts import _RISK_PREAMBLE
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


def test_risk_optimist_contains_recommended_level():
    from agent.prompts import RISK_OPTIMIST_INSTRUCTION
    formatted = RISK_OPTIMIST_INSTRUCTION.format(calibration_summary="x")
    assert "recommended_level" in formatted


def test_risk_pessimist_contains_recommended_level():
    from agent.prompts import RISK_PESSIMIST_INSTRUCTION
    formatted = RISK_PESSIMIST_INSTRUCTION.format(calibration_summary="x")
    assert "recommended_level" in formatted


def test_risk_preamble_mentions_risk_levels():
    from agent.prompts import _RISK_PREAMBLE
    text = _RISK_PREAMBLE.format(calibration_summary="")
    assert "HIGH" in text
    assert "MEDIUM" in text or "LOW" in text


def test_risk_preamble_has_regime_priors():
    from agent.prompts import _RISK_PREAMBLE
    text = _RISK_PREAMBLE.format(calibration_summary="")
    assert "CRISIS" in text
    assert "BULL_TREND" in text
    assert "LOW_VOL_RANGE" in text


def test_risk_pessimist_reads_optimist_verdict():
    from agent.prompts import RISK_PESSIMIST_INSTRUCTION
    formatted = RISK_PESSIMIST_INSTRUCTION.format(calibration_summary="x")
    assert "optimist" in formatted.lower()
    assert "strongest argument" in formatted.lower()


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
    max_strategy_cycles=3,
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


def test_coordinator_instruction_mentions_research_and_execution():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "research" in formatted.lower()
    assert "execution" in formatted.lower()


def test_coordinator_has_strategy_protocol():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "STRATEGY PROTOCOL" in formatted
    assert "strategy__list_strategies" in formatted
    assert "strategy__get_strategy" in formatted


def test_coordinator_mentions_cycle_count():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "cycle_count" in formatted
    assert "3" in formatted  # max_strategy_cycles


def test_coordinator_shows_tool_namespaces():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "market__*" in formatted
    assert "analysis__*" in formatted
    assert "research__*" in formatted
    assert "strategy__*" in formatted
    assert "forex__*" in formatted


def test_coordinator_no_execution_tools_exposed():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "execution__*" not in formatted


def test_coordinator_hitl_for_high_risk_any_mode():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "any mode" in formatted


def test_coordinator_write_ahead_before_execute():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    write_pos = formatted.find("Write-ahead")
    execute_pos = formatted.find("Execute")
    assert write_pos < execute_pos, "Write-ahead must appear before Execute in the cycle flow"


def test_coordinator_credentials_in_env_vars():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "environment variables" in formatted


def test_coordinator_state_keys_for_risk_agents():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert 'state["market_regime"]' in formatted
    assert 'state["macro_snapshot"]' in formatted
    assert 'state["analysis_snapshot"]' in formatted


def test_coordinator_risk_debate_template():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "Risk debate request template" in formatted


def test_coordinator_pending_order_state_key():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert 'state["pending_order"]' in formatted


def test_coordinator_asset_class_field():
    from agent.prompts import COORDINATOR_INSTRUCTION
    formatted = COORDINATOR_INSTRUCTION.format(**_COORD_BASE_KWARGS)
    assert "asset_class" in formatted


# ── Execution agent (BaseAgent — no LLM prompt) ───────────────────────────────

def test_execution_agent_module_importable():
    from agent.execution_agent import create_execution_agent, ExecutionAgent
    assert create_execution_agent is not None
    assert ExecutionAgent is not None


# ── Strategy tools ────────────────────────────────────────────────────────────

def test_strategy_tools_importable():
    from tools.strategy.tools import list_strategies, get_strategy, describe_tool
    assert list_strategies is not None
    assert get_strategy is not None
    assert describe_tool is not None
