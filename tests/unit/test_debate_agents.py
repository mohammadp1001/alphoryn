"""Unit tests for agent/debate_agents.py — parallel debate agent factories."""

from __future__ import annotations

# ── create_debate_optimist ────────────────────────────────────────────────────


def test_create_debate_optimist_returns_agent():
    from agent.debate_agents import create_debate_optimist

    agent = create_debate_optimist("No calibration data.")
    assert agent is not None
    assert agent.name == "debate_optimist"


def test_create_debate_optimist_default_model():
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.debate_agents import _OPTIMIST_MODEL, create_debate_optimist

    agent = create_debate_optimist("cal")
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == _OPTIMIST_MODEL


def test_create_debate_optimist_custom_model():
    from agent.debate_agents import create_debate_optimist

    agent = create_debate_optimist("cal", model="gemini-2.5-flash")
    assert agent.model == "gemini-2.5-flash"


def test_create_debate_optimist_has_read_file_tool():
    from agent.debate_agents import create_debate_optimist

    agent = create_debate_optimist("cal")
    assert len(agent.tools) == 1
    tool = agent.tools[0]
    tool_name = getattr(tool, "name", None) or getattr(tool.func, "__name__", "")
    assert tool_name == "read_file"


def test_create_debate_optimist_output_key():
    from agent.debate_agents import create_debate_optimist

    agent = create_debate_optimist("cal")
    assert agent.output_key == "optimist_verdict"


def test_create_debate_optimist_output_schema():
    from agent.debate_agents import create_debate_optimist
    from tools.schemas import RiskVerdictOutput

    agent = create_debate_optimist("cal")
    assert agent.output_schema is RiskVerdictOutput


# ── create_debate_pessimist ───────────────────────────────────────────────────


def test_create_debate_pessimist_returns_agent():
    from agent.debate_agents import create_debate_pessimist

    agent = create_debate_pessimist("No calibration data.")
    assert agent is not None
    assert agent.name == "debate_pessimist"


def test_create_debate_pessimist_default_model():
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.debate_agents import _PESSIMIST_MODEL, create_debate_pessimist

    agent = create_debate_pessimist("cal")
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == _PESSIMIST_MODEL


def test_create_debate_pessimist_custom_model():
    from agent.debate_agents import create_debate_pessimist

    agent = create_debate_pessimist("cal", model="gemini-2.5-flash")
    assert agent.model == "gemini-2.5-flash"


def test_create_debate_pessimist_has_read_file_tool():
    from agent.debate_agents import create_debate_pessimist

    agent = create_debate_pessimist("cal")
    assert len(agent.tools) == 1
    tool = agent.tools[0]
    tool_name = getattr(tool, "name", None) or getattr(tool.func, "__name__", "")
    assert tool_name == "read_file"


def test_create_debate_pessimist_output_key():
    from agent.debate_agents import create_debate_pessimist

    agent = create_debate_pessimist("cal")
    assert agent.output_key == "pessimist_verdict"


def test_create_debate_pessimist_output_schema():
    from agent.debate_agents import create_debate_pessimist
    from tools.schemas import RiskVerdictOutput

    agent = create_debate_pessimist("cal")
    assert agent.output_schema is RiskVerdictOutput


# ── models differ between optimist and pessimist ─────────────────────────────


def test_debate_agents_use_different_models():
    from agent.debate_agents import _OPTIMIST_MODEL, _PESSIMIST_MODEL

    assert _OPTIMIST_MODEL != _PESSIMIST_MODEL


# ── parallel invocation pattern ───────────────────────────────────────────────


def test_coordinator_instruction_mentions_parallel_risk_debate():
    from agent.prompts import COORDINATOR_INSTRUCTION

    formatted = COORDINATOR_INSTRUCTION.format(
        session_id="test-sess",
        mode="SEMI_AUTO",
        loss_limit_eur=500.0,
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
        universe="US_SECTOR_ETFS",
        symbols="XLK",
        exchange_tz="America/New_York",
        timeframe="1Day",
        session_expires_at="2026-06-13T20:00:00",
        max_strategy_cycles=3,
        allow_closed_market="false",
    )
    assert "risk_debate" in formatted or "debate" in formatted.lower()


def test_debate_json_validator_no_json_warns(caplog):
    import asyncio
    import logging
    from unittest.mock import MagicMock

    from agent.debate_agents import _make_json_validator_callback
    from tools.schemas import RiskVerdictOutput

    validator = _make_json_validator_callback("debate_optimist", RiskVerdictOutput)

    mock_response = MagicMock()
    mock_part = MagicMock()
    mock_part.text = "No JSON here at all."
    mock_response.content.parts = [mock_part]

    ctx = MagicMock()

    with caplog.at_level(logging.WARNING, logger="agent.debate_agents"):
        result = asyncio.run(validator(ctx, mock_response))

    assert result is None
    assert any("no_json_block" in r.message for r in caplog.records)


def test_debate_json_validator_invalid_json_warns(caplog):
    import asyncio
    import logging
    from unittest.mock import MagicMock

    from agent.debate_agents import _make_json_validator_callback
    from tools.schemas import RiskVerdictOutput

    validator = _make_json_validator_callback("debate_optimist", RiskVerdictOutput)

    mock_response = MagicMock()
    mock_part = MagicMock()
    mock_part.text = '{"recommended_level": "INVALID", "reasoning": 42}'
    mock_response.content.parts = [mock_part]

    ctx = MagicMock()

    with caplog.at_level(logging.WARNING, logger="agent.debate_agents"):
        result = asyncio.run(validator(ctx, mock_response))

    assert result is None


def test_debate_json_validator_empty_response_returns_none():
    import asyncio
    from unittest.mock import MagicMock

    from agent.debate_agents import _make_json_validator_callback
    from tools.schemas import RiskVerdictOutput

    validator = _make_json_validator_callback("debate_optimist", RiskVerdictOutput)

    mock_response = MagicMock()
    mock_response.content = None

    ctx = MagicMock()
    result = asyncio.run(validator(ctx, mock_response))
    assert result is None
