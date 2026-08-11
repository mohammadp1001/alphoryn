"""Unit tests for alphoryn/agents/responses.py.

One shared reader for every agent that parses a JSON answer out of a Gemini
response. It exists because main_agent and feedback_agent each grew their own
copy, the copies drifted, and the feedback agent's copy could never parse a
real reply - see test_a_fenced_answer_after_a_thought_is_the_live_failure.
"""

from unittest.mock import MagicMock

from alphoryn.agents.responses import extract_response_json, strip_fences

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _part(text: str | None, *, thought: bool | None = None) -> MagicMock:
    part = MagicMock()
    part.text = text
    part.thought = thought
    return part


# ---------------------------------------------------------------------------
# strip_fences
# ---------------------------------------------------------------------------


def test_plain_json_is_unchanged() -> None:
    assert strip_fences('{"a": 1}') == '{"a": 1}'


def test_json_tagged_fence_is_removed() -> None:
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_untagged_fence_is_removed() -> None:
    assert strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_fence_without_a_closing_tick_is_removed() -> None:
    assert strip_fences('```json\n{"a": 1}') == '{"a": 1}'


def test_text_that_merely_contains_backticks_is_untouched() -> None:
    assert strip_fences('{"a": "```"}') == '{"a": "```"}'


# ---------------------------------------------------------------------------
# extract_response_json
# ---------------------------------------------------------------------------


def test_a_single_plain_part_is_returned() -> None:
    assert extract_response_json([_part('{"a": 1}')]) == '{"a": 1}'


def test_a_thought_part_is_skipped() -> None:
    parts = [_part("my reasoning", thought=True), _part('{"a": 1}')]
    assert extract_response_json(parts) == '{"a": 1}'


def test_an_empty_part_is_skipped() -> None:
    """A tool-call part carries no text; taking it yields '' and fails at char 0."""
    assert extract_response_json([_part(""), _part('{"a": 1}')]) == '{"a": 1}'


def test_a_whitespace_only_part_is_skipped() -> None:
    assert extract_response_json([_part("   \n "), _part('{"a": 1}')]) == '{"a": 1}'


def test_a_part_with_no_text_attribute_is_skipped() -> None:
    assert extract_response_json([_part(None), _part('{"a": 1}')]) == '{"a": 1}'


def test_surrounding_whitespace_is_trimmed() -> None:
    assert extract_response_json([_part('\n  {"a": 1}  \n')]) == '{"a": 1}'


def test_nothing_usable_returns_none() -> None:
    assert extract_response_json([_part(""), _part(None)]) is None


def test_no_parts_at_all_returns_none() -> None:
    assert extract_response_json([]) is None


def test_only_a_thought_returns_none() -> None:
    assert extract_response_json([_part("reasoning", thought=True)]) is None


def test_the_first_usable_part_wins() -> None:
    assert extract_response_json([_part('{"a": 1}'), _part('{"b": 2}')]) == '{"a": 1}'


def test_a_fenced_answer_after_a_thought_is_the_live_failure() -> None:
    """Regression for the 2026-08-11 run.

    Gemini returned part[0] = a 4077-char thought summary and part[1] = the
    answer wrapped in ```json fences. feedback_agent skipped the thought
    correctly but then handed the fenced string straight to json.loads, which
    fails at character 0. A complete, correct evaluation was discarded three
    times and the position was filed EVALUATION_FAILED - the exact outcome
    FR-016a exists to prevent.
    """
    parts = [
        _part("Alright, let's break down what I'm thinking here...", thought=True),
        _part('```json\n{\n  "outcome_judgment": "CORRECT"\n}\n```'),
    ]
    assert extract_response_json(parts) == '{\n  "outcome_judgment": "CORRECT"\n}'
