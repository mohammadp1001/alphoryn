"""Unit tests for alphoryn/agents/prompts.py (T025 scope).

Verifies that the main agent system prompt contains all required elements:
- Snapshot isolation enforcement clause
- Regime recognition rules for both strategies
- Memory bank context format instructions
- SessionDecision output schema
- Correct structural constants
"""

from alphoryn.agents.prompts import (
    FEEDBACK_AGENT_SYSTEM_PROMPT,
    MAIN_AGENT_SYSTEM_PROMPT,
    MEAN_REVERSION_REGIME_RULES,
    MEMORY_CONTEXT_FORMAT,
    MOMENTUM_REGIME_RULES,
    OUTPUT_SCHEMA,
    SNAPSHOT_ISOLATION_CLAUSE,
)

# ---------------------------------------------------------------------------
# Module-level constants — existence and type
# ---------------------------------------------------------------------------


def test_main_agent_system_prompt_is_string() -> None:
    assert isinstance(MAIN_AGENT_SYSTEM_PROMPT, str)
    assert len(MAIN_AGENT_SYSTEM_PROMPT) > 100


def test_feedback_agent_system_prompt_is_string() -> None:
    assert isinstance(FEEDBACK_AGENT_SYSTEM_PROMPT, str)


def test_snapshot_isolation_clause_is_string() -> None:
    assert isinstance(SNAPSHOT_ISOLATION_CLAUSE, str)


# ---------------------------------------------------------------------------
# Snapshot isolation enforcement (constitution Principle V)
# ---------------------------------------------------------------------------


def test_snapshot_isolation_clause_forbids_second_call() -> None:
    assert "build_snapshot" in SNAPSHOT_ISOLATION_CLAUSE
    assert "Do not call any further market data tools" in SNAPSHOT_ISOLATION_CLAUSE


def test_main_prompt_contains_snapshot_isolation() -> None:
    assert SNAPSHOT_ISOLATION_CLAUSE in MAIN_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Mean reversion regime rules
# ---------------------------------------------------------------------------


def test_mean_reversion_rules_reference_adx() -> None:
    assert "adx_14" in MEAN_REVERSION_REGIME_RULES


def test_mean_reversion_rules_reference_rsi() -> None:
    assert "rsi_14" in MEAN_REVERSION_REGIME_RULES


def test_mean_reversion_rules_reference_bollinger() -> None:
    assert "bollinger_pct_b" in MEAN_REVERSION_REGIME_RULES


def test_mean_reversion_rules_reference_sma() -> None:
    assert "sma_20" in MEAN_REVERSION_REGIME_RULES


def test_mean_reversion_rules_reference_price_level_exit() -> None:
    assert "price_level" in MEAN_REVERSION_REGIME_RULES


def test_main_prompt_contains_mean_reversion_rules() -> None:
    assert MEAN_REVERSION_REGIME_RULES in MAIN_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Momentum regime rules
# ---------------------------------------------------------------------------


def test_momentum_rules_reference_adx() -> None:
    assert "adx_14" in MOMENTUM_REGIME_RULES


def test_momentum_rules_reference_macd() -> None:
    assert "macd_histogram" in MOMENTUM_REGIME_RULES


def test_momentum_rules_reference_ema_structure() -> None:
    assert "ema_20" in MOMENTUM_REGIME_RULES
    assert "ema_50" in MOMENTUM_REGIME_RULES


def test_momentum_rules_reference_trailing_stop_exit() -> None:
    assert "trailing_stop" in MOMENTUM_REGIME_RULES


def test_momentum_rules_reference_pullback_entry() -> None:
    assert "PULLBACK" in MOMENTUM_REGIME_RULES


def test_momentum_rules_reference_breakout_entry() -> None:
    assert "BREAKOUT" in MOMENTUM_REGIME_RULES


def test_main_prompt_contains_momentum_rules() -> None:
    assert MOMENTUM_REGIME_RULES in MAIN_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Memory bank context format
# ---------------------------------------------------------------------------


def test_memory_context_references_outcome_judgment() -> None:
    assert "outcome_judgment" in MEMORY_CONTEXT_FORMAT


def test_memory_context_references_correct_incorrect_neutral() -> None:
    assert "CORRECT" in MEMORY_CONTEXT_FORMAT
    assert "INCORRECT" in MEMORY_CONTEXT_FORMAT
    assert "NEUTRAL" in MEMORY_CONTEXT_FORMAT


def test_main_prompt_contains_memory_context() -> None:
    assert MEMORY_CONTEXT_FORMAT in MAIN_AGENT_SYSTEM_PROMPT


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
