"""Unit tests for alphoryn/agents/main_agent.py (T026 scope)."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from alphoryn.agents.main_agent import (
    MainAgent,
    MainAgentError,
    _build_prompt,
    _parse_decision,
    _strip_fences,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CANDLE_CLOSE_AT = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

_DECISION_DICT = {
    "session_id": "sess-001",
    "decisions": [
        {
            "ticker": "SPY",
            "action": "BUY",
            "strategy": "MEAN_REVERSION",
            "lot_size": 5,
            "exit_target": {"type": "price_level", "value": 450.0},
            "reasoning": "ADX low, price below SMA.",
        },
        {
            "ticker": "QQQ",
            "action": "HOLD",
            "strategy": "MOMENTUM",
            "lot_size": None,
            "exit_target": None,
            "reasoning": "No regime qualified.",
        },
    ],
}


def _make_event(
    *,
    is_final: bool = False,
    text: str | None = None,
    function_calls: list | None = None,
    function_responses: list | None = None,
) -> MagicMock:
    event = MagicMock()
    event.get_function_calls.return_value = function_calls or []
    event.get_function_responses.return_value = function_responses or []
    event.is_final_response.return_value = is_final
    if text is not None:
        event.content.parts = [MagicMock(text=text)]
    else:
        event.content = None
    return event


def _make_fc(name: str = "build_snapshot") -> MagicMock:
    fc = MagicMock()
    fc.name = name
    fc.args = {"tickers": ["SPY", "QQQ"], "candle_close_at": "2024-01-15T15:00:00+00:00"}
    return fc


def _make_fr(name: str = "build_snapshot") -> MagicMock:
    fr = MagicMock()
    fr.name = name
    fr.response = {"captured_at": "2024-01-15T15:00:00+00:00"}
    return fr


def _make_agent(mock_client: MagicMock | None = None) -> tuple[MainAgent, MagicMock]:
    if mock_client is None:
        mock_client = MagicMock()
    logger = MagicMock()
    with patch("alphoryn.agents.main_agent.LlmAgent"), \
         patch("alphoryn.agents.main_agent.load_skill_from_dir"), \
         patch("alphoryn.agents.main_agent.SkillToolset"):
        agent = MainAgent(mock_client, logger)
    return agent, logger


# ---------------------------------------------------------------------------
# MainAgent.__init__
# ---------------------------------------------------------------------------


def test_init_creates_llm_agent_with_model_and_tools() -> None:
    mock_client = MagicMock()
    logger = MagicMock()
    mock_toolset = MagicMock()
    with patch("alphoryn.agents.main_agent.LlmAgent") as mock_llm_cls, \
         patch("alphoryn.agents.main_agent.load_skill_from_dir"), \
         patch("alphoryn.agents.main_agent.SkillToolset", return_value=mock_toolset):
        MainAgent(mock_client, logger)
    mock_llm_cls.assert_called_once()
    kwargs = mock_llm_cls.call_args.kwargs
    assert kwargs["name"] == "alphoryn_main_agent"
    assert kwargs["model"] == "gemini-2.5-pro"
    assert mock_client.build_snapshot in kwargs["tools"]
    assert mock_toolset in kwargs["tools"]


def test_init_loads_all_five_skills() -> None:
    from alphoryn.agents.main_agent import _SKILL_NAMES
    mock_client = MagicMock()
    logger = MagicMock()
    with patch("alphoryn.agents.main_agent.LlmAgent"), \
         patch("alphoryn.agents.main_agent.load_skill_from_dir") as mock_load, \
         patch("alphoryn.agents.main_agent.SkillToolset"):
        MainAgent(mock_client, logger)
    assert mock_load.call_count == len(_SKILL_NAMES)
    loaded_names = [str(call.args[0]).split("skills")[-1].strip("/\\") for call in mock_load.call_args_list]
    for name in _SKILL_NAMES:
        assert any(name in n for n in loaded_names)


# ---------------------------------------------------------------------------
# decide — happy path
# ---------------------------------------------------------------------------


def test_decide_returns_session_decision_from_final_event() -> None:
    agent, _logger = _make_agent()
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        decision = agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    assert decision.session_id == "sess-001"
    assert decision.decisions[0].action == "BUY"
    assert decision.decisions[1].action == "HOLD"


def test_decide_emits_agent_decision_telemetry() -> None:
    agent, logger = _make_agent()
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "AGENT_DECISION" in emitted_types


def test_decide_passes_session_id_to_telemetry() -> None:
    agent, logger = _make_agent()
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        agent.decide("sess-xyz", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    for c in logger.emit.call_args_list:
        assert c.kwargs.get("session_id") == "sess-xyz"


# ---------------------------------------------------------------------------
# decide — tool call events
# ---------------------------------------------------------------------------


def test_decide_tool_call_event_emits_tool_call_telemetry() -> None:
    agent, logger = _make_agent()
    fc = _make_fc("build_snapshot")
    tool_call_event = _make_event(function_calls=[fc])
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([tool_call_event, final_event])

        agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "TOOL_CALL" in emitted_types


def test_decide_multiple_tool_calls_emit_multiple_tool_call_events() -> None:
    agent, logger = _make_agent()
    fc1 = _make_fc("build_snapshot")
    fc2 = _make_fc("build_snapshot")
    tool_call_event = _make_event(function_calls=[fc1, fc2])
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([tool_call_event, final_event])

        agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    tool_call_events = [
        c for c in logger.emit.call_args_list if c.args[0] == "TOOL_CALL"
    ]
    assert len(tool_call_events) == 2


# ---------------------------------------------------------------------------
# decide — tool response events
# ---------------------------------------------------------------------------


def test_decide_build_snapshot_response_emits_signal_snapshot_built() -> None:
    agent, logger = _make_agent()
    fr = _make_fr("build_snapshot")
    response_event = _make_event(function_responses=[fr])
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([response_event, final_event])

        agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "SIGNAL_SNAPSHOT_BUILT" in emitted_types


def test_decide_non_build_snapshot_response_does_not_emit_snapshot_built() -> None:
    agent, logger = _make_agent()
    fr = _make_fr("other_tool")
    response_event = _make_event(function_responses=[fr])
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([response_event, final_event])

        agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "SIGNAL_SNAPSHOT_BUILT" not in emitted_types


# ---------------------------------------------------------------------------
# decide — error paths
# ---------------------------------------------------------------------------


def test_decide_no_final_response_raises_main_agent_error() -> None:
    agent, _ = _make_agent()
    non_final_event = _make_event(is_final=False)

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([non_final_event])

        with pytest.raises(MainAgentError, match="no final response"):
            agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)


def test_decide_final_event_with_no_content_raises_main_agent_error() -> None:
    agent, _ = _make_agent()
    event = _make_event(is_final=True, text=None)

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([event])

        with pytest.raises(MainAgentError, match="no final response"):
            agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)


def test_decide_invalid_json_raises_main_agent_error() -> None:
    agent, _ = _make_agent()
    final_event = _make_event(is_final=True, text="not-valid-json{{{")

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        with pytest.raises(MainAgentError, match="not valid JSON"):
            agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)


def test_decide_invalid_decision_structure_raises_main_agent_error() -> None:
    agent, _ = _make_agent()
    bad_data = {"session_id": "sess-001", "decisions": "wrong"}
    final_event = _make_event(is_final=True, text=json.dumps(bad_data))

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        with pytest.raises(MainAgentError, match="Invalid SessionDecision"):
            agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)


# ---------------------------------------------------------------------------
# decide — memory entries
# ---------------------------------------------------------------------------


def test_decide_with_memory_entries_includes_them_in_runner_call() -> None:
    agent, _ = _make_agent()
    final_event = _make_event(is_final=True, text=json.dumps(_DECISION_DICT))
    entries = [{"ticker": "SPY", "outcome_judgment": "CORRECT"}]

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT, memory_entries=entries)

    # Verify run was called with Content containing memory_entries in the text
    run_call = mock_runner.run.call_args
    message_content = run_call.kwargs["new_message"]
    text = message_content.parts[0].text
    assert "memory_entries" in text
    assert "CORRECT" in text


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_contains_session_and_tickers_fields() -> None:
    prompt = _build_prompt("sess-1", ["SPY", "QQQ"], _CANDLE_CLOSE_AT, None)
    assert "session_id: sess-1" in prompt
    assert "tickers: SPY, QQQ" in prompt
    assert "candle_close_at:" in prompt


def test_build_prompt_without_memory_entries_excludes_memory_key() -> None:
    prompt = _build_prompt("sess-1", ["SPY", "QQQ"], _CANDLE_CLOSE_AT, None)
    assert "memory_entries" not in prompt


def test_build_prompt_with_memory_entries_includes_json() -> None:
    entries = [{"ticker": "SPY", "outcome_judgment": "INCORRECT"}]
    prompt = _build_prompt("sess-1", ["SPY", "QQQ"], _CANDLE_CLOSE_AT, entries)
    assert "memory_entries" in prompt
    assert "INCORRECT" in prompt


def test_build_prompt_with_empty_memory_entries_excludes_key() -> None:
    prompt = _build_prompt("sess-1", ["SPY", "QQQ"], _CANDLE_CLOSE_AT, [])
    assert "memory_entries" not in prompt


# ---------------------------------------------------------------------------
# _parse_decision
# ---------------------------------------------------------------------------


def test_parse_decision_returns_session_decision() -> None:
    decision = _parse_decision(_DECISION_DICT)
    assert decision.session_id == "sess-001"
    assert decision.decisions[0].ticker == "SPY"
    assert decision.decisions[1].ticker == "QQQ"


def test_parse_decision_missing_key_raises_main_agent_error() -> None:
    bad_data = {"session_id": "sess-001"}
    with pytest.raises(MainAgentError, match="Invalid SessionDecision"):
        _parse_decision(bad_data)


def test_parse_decision_non_list_decisions_raises_main_agent_error() -> None:
    bad_data = {
        "session_id": "sess-001",
        "decisions": "not-a-list",
    }
    with pytest.raises(MainAgentError, match="Invalid SessionDecision"):
        _parse_decision(bad_data)


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_plain_json_unchanged() -> None:
    raw = '{"a": 1}'
    assert _strip_fences(raw) == raw


def test_strip_fences_removes_json_code_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert _strip_fences(raw) == '{"a": 1}'


def test_strip_fences_removes_plain_code_fence() -> None:
    raw = '```\n{"a": 1}\n```'
    assert _strip_fences(raw) == '{"a": 1}'


def test_strip_fences_fence_without_closing_tick() -> None:
    raw = '```json\n{"a": 1}'
    assert _strip_fences(raw) == '{"a": 1}'


# ---------------------------------------------------------------------------
# decide — empty text part skipped (Gemini 2.5 Pro thinking tokens)
# ---------------------------------------------------------------------------


def test_decide_empty_first_part_uses_second_part() -> None:
    """Empty parts[0].text (thinking token) must be skipped; JSON in parts[1] is used."""
    agent, _ = _make_agent()
    empty_part = MagicMock(text="")
    json_part = MagicMock(text=json.dumps(_DECISION_DICT))
    event = MagicMock()
    event.get_function_calls.return_value = []
    event.get_function_responses.return_value = []
    event.is_final_response.return_value = True
    event.content.parts = [empty_part, json_part]

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([event])

        decision = agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    assert decision.session_id == "sess-001"


def test_decide_all_empty_parts_raises_main_agent_error() -> None:
    """All empty text parts → treated as no final response."""
    agent, _ = _make_agent()
    event = MagicMock()
    event.get_function_calls.return_value = []
    event.get_function_responses.return_value = []
    event.is_final_response.return_value = True
    event.content.parts = [MagicMock(text=""), MagicMock(text="")]

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([event])

        with pytest.raises(MainAgentError, match="no final response"):
            agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)


def test_decide_markdown_fenced_json_is_parsed_correctly() -> None:
    """LLM wraps JSON in ```json fence; must be stripped before parsing."""
    agent, _ = _make_agent()
    fenced = f"```json\n{json.dumps(_DECISION_DICT)}\n```"
    final_event = _make_event(is_final=True, text=fenced)

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        decision = agent.decide("sess-001", ["SPY", "QQQ"], _CANDLE_CLOSE_AT)

    assert decision.session_id == "sess-001"
