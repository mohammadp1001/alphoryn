"""Unit tests for alphoryn/agents/feedback_agent.py (T039 scope).

All tests use stub/mock dependencies — zero actual LLM calls.
InMemoryRunner is patched at the class level with synthetic events.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alphoryn.agents.feedback_agent import (
    FeedbackAgent,
    FeedbackAgentError,
    FeedbackInput,
)

_extract_thesis = FeedbackAgent._extract_thesis
_build_prompt = FeedbackAgent._build_prompt
_parse_result = FeedbackAgent._parse_result

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_INPUT = FeedbackInput(
    position_id=42,
    session_id="run-1/session-0001",
    etf="SPY",
    strategy="MEAN_REVERSION",
    html_report_path="/reports/run-1/run-1-session-0001.html",
    entry_price=450.0,
    exit_price=458.0,
    exit_reason="PROFIT_TARGET",
)

_RESULT_DICT = {
    "outcome_judgment": "CORRECT",
    "thesis_summary": "Price was expected to mean-revert to SMA_20.",
    "reasoning": "Price rose from entry to exit as predicted by mean-reversion thesis.",
}


def _make_event(*, is_final: bool = False, text: str | None = None) -> MagicMock:
    event = MagicMock()
    event.get_function_calls.return_value = []
    event.get_function_responses.return_value = []
    event.is_final_response.return_value = is_final
    if text is not None:
        event.content.parts = [MagicMock(text=text)]
    else:
        event.content = None
    return event


def _make_agent() -> tuple[FeedbackAgent, MagicMock, MagicMock, MagicMock]:
    market_data = MagicMock()
    market_data.get_latest_price.return_value = 460.0
    bank = MagicMock()
    logger = MagicMock()
    with patch("alphoryn.agents.feedback_agent.LlmAgent"):
        agent = FeedbackAgent(market_data, bank, logger)
    return agent, market_data, bank, logger


def _run_evaluate(agent: FeedbackAgent, *, result_dict: dict | None = None) -> None:
    if result_dict is None:
        result_dict = _RESULT_DICT
    final_event = _make_event(is_final=True, text=json.dumps(result_dict))
    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="Price was oversold."),
    ):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])
        agent.evaluate(_INPUT, "run-1/session-0003")


# ---------------------------------------------------------------------------
# _extract_thesis
# ---------------------------------------------------------------------------


def test_extract_thesis_finds_investment_thesis_section(tmp_path: Path) -> None:
    html = (
        "<html><body>"
        '<section id="investment-thesis"><p>ADX was low, price oversold.</p></section>'
        "</body></html>"
    )
    path = tmp_path / "report.html"
    path.write_text(html, encoding="utf-8")
    result = _extract_thesis(str(path))
    assert "ADX was low" in result
    assert "<p>" not in result  # HTML tags stripped


def test_extract_thesis_falls_back_to_full_html_when_section_missing(tmp_path: Path) -> None:
    html = "<html><body><p>No thesis section here.</p></body></html>"
    path = tmp_path / "report.html"
    path.write_text(html, encoding="utf-8")
    result = _extract_thesis(str(path))
    assert "No thesis section here" in result


def test_extract_thesis_handles_single_quotes_in_id(tmp_path: Path) -> None:
    html = "<section id='investment-thesis'>Single quote ID thesis.</section>"
    path = tmp_path / "report.html"
    path.write_text(html, encoding="utf-8")
    result = _extract_thesis(str(path))
    assert "Single quote ID thesis" in result


def test_extract_thesis_is_static_method() -> None:
    assert isinstance(
        FeedbackAgent.__dict__["_extract_thesis"], staticmethod
    )


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_includes_etf() -> None:
    prompt = _build_prompt(_INPUT, "thesis text", 460.0)
    assert "SPY" in prompt


def test_build_prompt_includes_thesis() -> None:
    prompt = _build_prompt(_INPUT, "ADX was low, price oversold.", 460.0)
    assert "ADX was low" in prompt


def test_build_prompt_includes_exit_reason() -> None:
    prompt = _build_prompt(_INPUT, "thesis text", 460.0)
    assert "PROFIT_TARGET" in prompt


def test_build_prompt_includes_current_price() -> None:
    prompt = _build_prompt(_INPUT, "thesis text", 461.23)
    assert "461.23" in prompt


def test_build_prompt_includes_pnl_pct() -> None:
    # entry 450, exit 458 → (8/450)*100 = 1.78%
    prompt = _build_prompt(_INPUT, "thesis text", 460.0)
    assert "1.78" in prompt


# ---------------------------------------------------------------------------
# _parse_result
# ---------------------------------------------------------------------------


def test_parse_result_returns_dict_for_valid_json() -> None:
    result = _parse_result(json.dumps(_RESULT_DICT))
    assert result["outcome_judgment"] == "CORRECT"


def test_parse_result_raises_on_invalid_json() -> None:
    with pytest.raises(FeedbackAgentError, match="Invalid JSON"):
        _parse_result("{not valid json")


def test_parse_result_raises_on_missing_field() -> None:
    incomplete = {"outcome_judgment": "CORRECT"}
    with pytest.raises(FeedbackAgentError, match="Missing fields"):
        _parse_result(json.dumps(incomplete))


def test_parse_result_raises_on_invalid_judgment() -> None:
    invalid = {**_RESULT_DICT, "outcome_judgment": "WRONG"}
    with pytest.raises(FeedbackAgentError, match="Invalid outcome_judgment"):
        _parse_result(json.dumps(invalid))


@pytest.mark.parametrize("judgment", ["CORRECT", "INCORRECT", "NEUTRAL"])
def test_parse_result_accepts_all_valid_judgments(judgment: str) -> None:
    data = {**_RESULT_DICT, "outcome_judgment": judgment}
    result = _parse_result(json.dumps(data))
    assert result["outcome_judgment"] == judgment


# ---------------------------------------------------------------------------
# FeedbackAgent.__init__
# ---------------------------------------------------------------------------


def test_init_creates_llm_agent_with_model() -> None:
    market_data = MagicMock()
    bank = MagicMock()
    logger = MagicMock()
    with patch("alphoryn.agents.feedback_agent.LlmAgent") as mock_llm_cls:
        FeedbackAgent(market_data, bank, logger)
    mock_llm_cls.assert_called_once()
    kwargs = mock_llm_cls.call_args.kwargs
    assert kwargs["model"] == "gemini-2.0-flash"
    assert kwargs["name"] == "alphoryn_feedback_agent"


# ---------------------------------------------------------------------------
# evaluate — happy path
# ---------------------------------------------------------------------------


def test_evaluate_writes_feedback_evaluation_to_bank() -> None:
    agent, _, bank, _ = _make_agent()
    _run_evaluate(agent)
    bank.write_feedback_evaluation.assert_called_once()


def test_evaluate_sets_position_status_evaluated() -> None:
    agent, _, bank, _ = _make_agent()
    _run_evaluate(agent)
    _, status_arg = bank.write_feedback_evaluation.call_args.args
    assert status_arg == "EVALUATED"


def test_evaluate_updates_memory_entry_judgment() -> None:
    agent, _, bank, _ = _make_agent()
    _run_evaluate(agent)
    bank.update_memory_entry_judgment.assert_called_once()
    kwargs = bank.update_memory_entry_judgment.call_args.kwargs
    assert kwargs["outcome_judgment"] == "CORRECT"
    assert kwargs["etf"] == "SPY"


def test_evaluate_emits_agent_decision_telemetry() -> None:
    agent, _, _, logger = _make_agent()
    _run_evaluate(agent)
    emitted = [c.args[0] for c in logger.emit.call_args_list]
    assert "AGENT_DECISION" in emitted


def test_evaluate_passes_judgment_to_agent_decision_event() -> None:
    agent, _, _, logger = _make_agent()
    _run_evaluate(agent)
    decision_calls = [c for c in logger.emit.call_args_list if c.args[0] == "AGENT_DECISION"]
    assert len(decision_calls) == 1
    payload = decision_calls[0].args[2]
    assert payload["outcome_judgment"] == "CORRECT"


def test_evaluate_correct_judgment() -> None:
    agent, _, bank, _ = _make_agent()
    _run_evaluate(agent, result_dict={**_RESULT_DICT, "outcome_judgment": "CORRECT"})
    evaluation_arg = bank.write_feedback_evaluation.call_args.args[0]
    assert evaluation_arg.outcome_judgment == "CORRECT"


def test_evaluate_incorrect_judgment() -> None:
    agent, _, bank, _ = _make_agent()
    _run_evaluate(agent, result_dict={**_RESULT_DICT, "outcome_judgment": "INCORRECT"})
    evaluation_arg = bank.write_feedback_evaluation.call_args.args[0]
    assert evaluation_arg.outcome_judgment == "INCORRECT"


def test_evaluate_neutral_judgment() -> None:
    agent, _, bank, _ = _make_agent()
    _run_evaluate(agent, result_dict={**_RESULT_DICT, "outcome_judgment": "NEUTRAL"})
    evaluation_arg = bank.write_feedback_evaluation.call_args.args[0]
    assert evaluation_arg.outcome_judgment == "NEUTRAL"


def test_evaluate_populates_thesis_summary() -> None:
    agent, _, bank, _ = _make_agent()
    _run_evaluate(agent)
    evaluation_arg = bank.write_feedback_evaluation.call_args.args[0]
    assert evaluation_arg.thesis_summary == _RESULT_DICT["thesis_summary"]


def test_evaluate_calls_get_latest_price() -> None:
    agent, market_data, _, _ = _make_agent()
    _run_evaluate(agent)
    market_data.get_latest_price.assert_called_once_with("SPY")


# ---------------------------------------------------------------------------
# evaluate — no final response raises internally, retry kicks in
# ---------------------------------------------------------------------------


def test_evaluate_no_final_response_triggers_retry() -> None:
    agent, _, bank, logger = _make_agent()

    call_count = [0]

    def make_failing_runner():
        mock = MagicMock()
        # First two calls produce no final response; third succeeds
        def run_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                return iter([_make_event(is_final=False)])
            return iter([_make_event(is_final=True, text=json.dumps(_RESULT_DICT))])
        mock.run.side_effect = run_side_effect
        return mock

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis text"),
    ):
        mock_runner_cls.side_effect = lambda **kwargs: make_failing_runner()
        agent.evaluate(_INPUT, "run-1/session-0003")

    bank.write_feedback_evaluation.assert_called_once()
    assert call_count[0] == 3  # retried twice, succeeded on 3rd


# ---------------------------------------------------------------------------
# evaluate — 3-retry failure → EVALUATION_FAILED
# ---------------------------------------------------------------------------


def test_evaluate_three_failures_sets_evaluation_failed_status() -> None:
    agent, _, bank, _ = _make_agent()

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis text"),
    ):
        mock_runner_cls.return_value.run.return_value = iter(
            [_make_event(is_final=False)]  # no final response → always fails
        )
        agent.evaluate(_INPUT, "run-1/session-0003")

    _, status_arg = bank.write_feedback_evaluation.call_args.args
    assert status_arg == "EVALUATION_FAILED"


def test_evaluate_three_failures_emits_evaluation_failed_telemetry() -> None:
    agent, _, _, logger = _make_agent()

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis text"),
    ):
        mock_runner_cls.return_value.run.return_value = iter([_make_event(is_final=False)])
        agent.evaluate(_INPUT, "run-1/session-0003")

    emitted = [c.args[0] for c in logger.emit.call_args_list]
    assert "EVALUATION_FAILED" in emitted


def test_evaluate_three_failures_does_not_update_memory_entry() -> None:
    agent, _, bank, _ = _make_agent()

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis text"),
    ):
        mock_runner_cls.return_value.run.return_value = iter([_make_event(is_final=False)])
        agent.evaluate(_INPUT, "run-1/session-0003")

    bank.update_memory_entry_judgment.assert_not_called()


def test_evaluate_three_failures_runner_called_three_times() -> None:
    agent, _, _, _ = _make_agent()

    # Each InMemoryRunner instance produces no final response
    runner_instances = []

    def make_runner(**kwargs):
        m = MagicMock()
        m.run.return_value = iter([_make_event(is_final=False)])
        runner_instances.append(m)
        return m

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner", side_effect=make_runner),
        patch.object(agent, "_extract_thesis", return_value="thesis text"),
    ):
        agent.evaluate(_INPUT, "run-1/session-0003")

    assert len(runner_instances) == 3


def test_evaluate_three_failures_evaluation_written_once() -> None:
    agent, _, bank, _ = _make_agent()

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis text"),
    ):
        mock_runner_cls.return_value.run.return_value = iter([_make_event(is_final=False)])
        agent.evaluate(_INPUT, "run-1/session-0003")

    bank.write_feedback_evaluation.assert_called_once()


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def test_feedback_agent_system_prompt_is_non_empty() -> None:
    from alphoryn.agents.prompts import FEEDBACK_AGENT_SYSTEM_PROMPT

    assert len(FEEDBACK_AGENT_SYSTEM_PROMPT) > 100


def test_feedback_agent_system_prompt_mentions_judgment_values() -> None:
    from alphoryn.agents.prompts import FEEDBACK_AGENT_SYSTEM_PROMPT

    for val in ("CORRECT", "INCORRECT", "NEUTRAL"):
        assert val in FEEDBACK_AGENT_SYSTEM_PROMPT


def test_feedback_agent_system_prompt_mentions_investment_thesis() -> None:
    from alphoryn.agents.prompts import FEEDBACK_AGENT_SYSTEM_PROMPT

    prompt_lower = FEEDBACK_AGENT_SYSTEM_PROMPT.lower()
    assert "investment-thesis" in prompt_lower or "thesis" in prompt_lower
