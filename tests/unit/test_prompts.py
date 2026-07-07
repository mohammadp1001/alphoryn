"""Unit tests for alphoryn/agents/prompts.py.

Verifies the minimal main agent system prompt contains the required structural
elements: snapshot isolation clause, skill-based workflow, and output schema.
Strategy rules are no longer in the prompt — they live in skill files.
"""

from alphoryn.agents.prompts import (
    FEEDBACK_AGENT_SYSTEM_PROMPT,
    MAIN_AGENT_SYSTEM_PROMPT,
    OUTPUT_SCHEMA,
    SNAPSHOT_ISOLATION_CLAUSE,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_main_agent_system_prompt_is_string() -> None:
    assert isinstance(MAIN_AGENT_SYSTEM_PROMPT, str)
    assert len(MAIN_AGENT_SYSTEM_PROMPT) > 50


def test_feedback_agent_system_prompt_is_string() -> None:
    assert isinstance(FEEDBACK_AGENT_SYSTEM_PROMPT, str)


def test_snapshot_isolation_clause_is_string() -> None:
    assert isinstance(SNAPSHOT_ISOLATION_CLAUSE, str)


# ---------------------------------------------------------------------------
# Snapshot isolation (constitution Principle V)
# ---------------------------------------------------------------------------


def test_snapshot_isolation_clause_references_build_snapshot() -> None:
    assert "build_snapshot" in SNAPSHOT_ISOLATION_CLAUSE


def test_snapshot_isolation_clause_forbids_second_call() -> None:
    clause = SNAPSHOT_ISOLATION_CLAUSE.lower()
    assert "not" in clause and ("again" in clause or "once" in clause)


def test_main_prompt_contains_snapshot_isolation() -> None:
    assert SNAPSHOT_ISOLATION_CLAUSE in MAIN_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Skill references — strategy rules live in skill files, not in the prompt
# ---------------------------------------------------------------------------


def test_main_prompt_references_identify_regime_skill() -> None:
    assert "identify_regime" in MAIN_AGENT_SYSTEM_PROMPT


def test_main_prompt_references_mean_reversion_entry_skill() -> None:
    assert "mean_reversion_entry" in MAIN_AGENT_SYSTEM_PROMPT


def test_main_prompt_references_momentum_entry_skill() -> None:
    assert "momentum_entry" in MAIN_AGENT_SYSTEM_PROMPT


def test_main_prompt_references_size_position_skill() -> None:
    assert "size_position" in MAIN_AGENT_SYSTEM_PROMPT


def test_main_prompt_references_read_memory_skill() -> None:
    assert "read_memory" in MAIN_AGENT_SYSTEM_PROMPT


def test_main_prompt_references_build_snapshot_tool() -> None:
    assert "build_snapshot" in MAIN_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


def test_output_schema_references_session_decision_fields() -> None:
    assert "session_id" in OUTPUT_SCHEMA
    assert "etf1" in OUTPUT_SCHEMA
    assert "etf2" in OUTPUT_SCHEMA
    assert "action" in OUTPUT_SCHEMA
    assert "strategy" in OUTPUT_SCHEMA
    assert "lot_size" in OUTPUT_SCHEMA
    assert "exit_target" in OUTPUT_SCHEMA
    assert "reasoning" in OUTPUT_SCHEMA


def test_output_schema_references_all_three_actions() -> None:
    assert "BUY" in OUTPUT_SCHEMA
    assert "SELL" in OUTPUT_SCHEMA
    assert "HOLD" in OUTPUT_SCHEMA


def test_output_schema_references_both_strategies() -> None:
    assert "MEAN_REVERSION" in OUTPUT_SCHEMA
    assert "MOMENTUM" in OUTPUT_SCHEMA


def test_main_prompt_contains_output_schema() -> None:
    assert OUTPUT_SCHEMA in MAIN_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# No strategy rules in the prompt (they belong in skill files)
# ---------------------------------------------------------------------------


def test_main_prompt_does_not_contain_regime_thresholds() -> None:
    assert "adx_14 > 25" not in MAIN_AGENT_SYSTEM_PROMPT
    assert "adx_14 < 25" not in MAIN_AGENT_SYSTEM_PROMPT
    assert "bollinger_pct_b < 0.25" not in MAIN_AGENT_SYSTEM_PROMPT
    assert "rsi_14 < 40" not in MAIN_AGENT_SYSTEM_PROMPT
