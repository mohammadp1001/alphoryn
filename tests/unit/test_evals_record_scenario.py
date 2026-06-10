"""Unit tests for evals.record_scenario — session recording utilities."""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest

# ── _ts ───────────────────────────────────────────────────────────────────────

def test_ts_returns_iso_string():
    from evals.record_scenario import _ts
    ts = _ts()
    assert "T" in ts  # ISO 8601 format with time separator


# ── _content_to_dict ──────────────────────────────────────────────────────────

def test_content_to_dict_none():
    from evals.record_scenario import _content_to_dict
    assert _content_to_dict(None) == {}


def test_content_to_dict_already_dict():
    from evals.record_scenario import _content_to_dict
    d = {"parts": [{"text": "hello"}]}
    assert _content_to_dict(d) == d


def test_content_to_dict_text_part():
    from evals.record_scenario import _content_to_dict
    part = MagicMock()
    part.text = "hello world"
    part.function_call = None
    part.function_response = None

    content = MagicMock()
    content.parts = [part]

    result = _content_to_dict(content)
    assert result == {"parts": [{"text": "hello world"}]}


def test_content_to_dict_function_call_part():
    from evals.record_scenario import _content_to_dict
    fc = MagicMock()
    fc.name = "write_trade"
    fc.args = {"symbol": "XLK"}

    part = MagicMock()
    part.text = None
    part.function_call = fc
    part.function_response = None

    content = MagicMock()
    content.parts = [part]

    result = _content_to_dict(content)
    assert result["parts"][0]["function_call"]["name"] == "write_trade"
    assert result["parts"][0]["function_call"]["args"] == {"symbol": "XLK"}


def test_content_to_dict_function_response_part():
    from evals.record_scenario import _content_to_dict
    fr = MagicMock()
    fr.name = "write_trade"
    fr.response = {"trade_id": "t-001"}

    part = MagicMock()
    part.text = None
    part.function_call = None
    part.function_response = fr

    content = MagicMock()
    content.parts = [part]

    result = _content_to_dict(content)
    assert result["parts"][0]["function_response"]["name"] == "write_trade"
    assert result["parts"][0]["function_response"]["response"] == {"trade_id": "t-001"}


def test_content_to_dict_empty_part_excluded():
    """Parts with no text/function_call/function_response are excluded."""
    from evals.record_scenario import _content_to_dict
    part = MagicMock()
    part.text = None
    part.function_call = None
    part.function_response = None

    content = MagicMock()
    content.parts = [part]

    result = _content_to_dict(content)
    assert result == {"parts": []}


def test_content_to_dict_no_parts_attr():
    """Objects without .parts return {'parts': []}."""
    from evals.record_scenario import _content_to_dict
    obj = MagicMock(spec=[])  # no 'parts' attribute
    result = _content_to_dict(obj)
    assert result == {"parts": []}


# ── events_to_trace ───────────────────────────────────────────────────────────

def _make_event(author: str, text: str = ""):
    e = MagicMock()
    e.author = author
    content = MagicMock()
    part = MagicMock()
    part.text = text
    part.function_call = None
    part.function_response = None
    content.parts = [part] if text else []
    e.content = content
    return e


def test_events_to_trace_single_turn():
    from evals.record_scenario import events_to_trace
    events = [
        _make_event("user", "Hello"),
        _make_event("coordinator", "Working on it"),
    ]
    result = events_to_trace("sess-1", events, agent_id="coordinator")
    assert len(result["turns"]) == 1
    assert result["turns"][0]["turn_index"] == 0
    assert "coordinator" in result["agents"]


def test_events_to_trace_multi_turn():
    """Multiple user messages → multiple turns."""
    from evals.record_scenario import events_to_trace
    events = [
        _make_event("user", "First message"),
        _make_event("coordinator", "Response 1"),
        _make_event("user", "Second message"),
        _make_event("coordinator", "Response 2"),
    ]
    result = events_to_trace("sess-mt", events)
    assert len(result["turns"]) == 2
    assert result["turns"][1]["turn_index"] == 1


def test_events_to_trace_empty_events():
    from evals.record_scenario import events_to_trace
    result = events_to_trace("sess-empty", [])
    assert result["turns"] == []


def test_events_to_trace_no_user_event():
    """Only agent events — all go into turn 0."""
    from evals.record_scenario import events_to_trace
    events = [
        _make_event("coordinator", "Done"),
        _make_event("tool", "result"),
    ]
    result = events_to_trace("sess-nouser", events)
    assert len(result["turns"]) == 1


# ── record_from_runner ────────────────────────────────────────────────────────

def test_record_from_runner_returns_dataset():
    from evals.record_scenario import record_from_runner

    mock_runner = MagicMock()
    mock_session = MagicMock()
    event = _make_event("user", "trade XLK")
    mock_session.events = [event]
    mock_runner.session_service.get_session.return_value = mock_session
    mock_runner.app_name = "alphoryn"

    result = record_from_runner(
        runner=mock_runner,
        session_id="sess-runner",
        case_id="test_case",
        agent_instruction="You are coordinator",
    )

    assert len(result["eval_cases"]) == 1
    assert result["eval_cases"][0]["eval_case_id"] == "test_case"


def test_record_from_runner_raises_if_session_not_found():
    from evals.record_scenario import record_from_runner

    mock_runner = MagicMock()
    mock_runner.session_service.get_session.return_value = None
    mock_runner.app_name = "alphoryn"

    with pytest.raises(ValueError, match="not found"):
        record_from_runner(mock_runner, "missing-id", "case-1")


def test_record_from_runner_writes_output_file(tmp_path):
    from evals.record_scenario import record_from_runner

    mock_runner = MagicMock()
    mock_session = MagicMock()
    mock_session.events = [_make_event("user", "start")]
    mock_runner.session_service.get_session.return_value = mock_session
    mock_runner.app_name = "alphoryn"

    out_file = tmp_path / "fixture.json"
    record_from_runner(
        runner=mock_runner,
        session_id="sess-file",
        case_id="file_case",
        output_path=out_file,
    )

    assert out_file.exists()
    written = json.loads(out_file.read_text())
    assert written["eval_cases"][0]["eval_case_id"] == "file_case"


# ── record_from_events_file ───────────────────────────────────────────────────

def test_record_from_events_file_basic(tmp_path):
    from evals.record_scenario import record_from_events_file

    events_file = tmp_path / "events.jsonl"
    lines = [
        json.dumps({"author": "user", "content": {"parts": [{"text": "start"}]}}),
        json.dumps({"author": "coordinator", "content": {"parts": [{"text": "ok"}]}}),
    ]
    events_file.write_text("\n".join(lines))

    result = record_from_events_file(
        events_file=events_file,
        case_id="events_case",
        session_id="sess-ev",
    )

    assert result["eval_cases"][0]["eval_case_id"] == "events_case"


def test_record_from_events_file_writes_output(tmp_path):
    from evals.record_scenario import record_from_events_file

    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps({"author": "user", "content": {"parts": [{"text": "hi"}]}})
    )
    out_file = tmp_path / "out.json"

    record_from_events_file(
        events_file=events_file,
        case_id="write_case",
        output_path=out_file,
    )
    assert out_file.exists()
    written = json.loads(out_file.read_text())
    assert written["eval_cases"][0]["eval_case_id"] == "write_case"


def test_record_from_events_file_ignores_blank_lines(tmp_path):
    from evals.record_scenario import record_from_events_file

    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps({"author": "user", "content": {}}) + "\n\n" +
        json.dumps({"author": "coordinator", "content": {}})
    )

    result = record_from_events_file(events_file=events_file, case_id="blank_case")
    # Should not raise; blank lines are skipped
    assert len(result["eval_cases"]) == 1


# ── _main (CLI entry point) ───────────────────────────────────────────────────

def test_main_missing_events_file_exits(tmp_path, capsys):
    from evals.record_scenario import _main

    with pytest.raises(SystemExit) as exc_info:
        _main(["--case-id", "x", "--output", str(tmp_path / "out.json")])
    assert exc_info.value.code == 1


def test_main_with_events_file(tmp_path):
    from evals.record_scenario import _main

    events_file = tmp_path / "ev.jsonl"
    events_file.write_text(
        json.dumps({"author": "user", "content": {"parts": [{"text": "trade now"}]}})
    )
    out_file = tmp_path / "out.json"

    _main([
        "--case-id", "cli_case",
        "--output", str(out_file),
        "--events-file", str(events_file),
        "--session-id", "cli-sess",
        "--instruction", "You are coordinator",
    ])

    assert out_file.exists()
    written = json.loads(out_file.read_text())
    assert written["eval_cases"][0]["eval_case_id"] == "cli_case"


def test_main_dunder_calls_main(tmp_path):
    """__main__ block calls _main() which in turn invokes record_from_events_file."""
    import runpy

    events_file = tmp_path / "dunder_ev.jsonl"
    events_file.write_text(
        json.dumps({"author": "user", "content": {"parts": [{"text": "go"}]}})
    )
    out_file = tmp_path / "dunder_out.json"

    saved_argv = sys.argv[:]
    sys.argv = [
        "record_scenario",
        "--case-id", "dunder_case",
        "--output", str(out_file),
        "--events-file", str(events_file),
    ]
    try:
        runpy.run_module("evals.record_scenario", run_name="__main__", alter_sys=False)
    finally:
        sys.argv = saved_argv

    assert out_file.exists()
    written = json.loads(out_file.read_text())
    assert written["eval_cases"][0]["eval_case_id"] == "dunder_case"
