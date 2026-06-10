"""Unit tests for evals.harness — dataset loading/validation utilities."""
from __future__ import annotations

import json
import runpy
from unittest.mock import patch

# ── load_dataset ──────────────────────────────────────────────────────────────

def test_load_dataset_returns_dict(tmp_path):
    from evals.harness import load_dataset
    data = {"eval_cases": [{"eval_case_id": "test1", "prompt": {"role": "user"}}]}
    f = tmp_path / "ds.json"
    f.write_text(json.dumps(data))
    result = load_dataset(f)
    assert result == data


# ── list_datasets ─────────────────────────────────────────────────────────────

def test_list_datasets_returns_json_files(tmp_path):
    from evals import harness
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.json").write_text("{}")
    (tmp_path / "c.txt").write_text("ignore")
    with patch.object(harness, "DATASETS_DIR", tmp_path):
        result = harness.list_datasets()
    names = [p.name for p in result]
    assert "a.json" in names
    assert "b.json" in names
    assert "c.txt" not in names


# ── validate_trace_structure ──────────────────────────────────────────────────

def test_validate_trace_structure_valid_prompt_case():
    from evals.harness import validate_trace_structure
    dataset = {"eval_cases": [{"eval_case_id": "c1", "prompt": {"role": "user"}}]}
    assert validate_trace_structure(dataset) == []


def test_validate_trace_structure_missing_both_fields():
    from evals.harness import validate_trace_structure
    dataset = {"eval_cases": [{"eval_case_id": "c1"}]}
    errors = validate_trace_structure(dataset)
    assert any("missing both" in e for e in errors)


def test_validate_trace_structure_agent_data_missing_agents():
    from evals.harness import validate_trace_structure
    dataset = {"eval_cases": [{"eval_case_id": "c1", "agent_data": {"turns": []}}]}
    errors = validate_trace_structure(dataset)
    assert any("missing 'agents'" in e for e in errors)


def test_validate_trace_structure_agent_data_missing_turns():
    """Line 50: agent_data missing 'turns' produces error."""
    from evals.harness import validate_trace_structure
    dataset = {"eval_cases": [{"eval_case_id": "c1", "agent_data": {"agents": {}}}]}
    errors = validate_trace_structure(dataset)
    assert any("missing 'turns'" in e for e in errors)


def test_validate_trace_structure_turn_missing_turn_index():
    from evals.harness import validate_trace_structure
    dataset = {
        "eval_cases": [{
            "eval_case_id": "c1",
            "agent_data": {
                "agents": {"a": {}},
                "turns": [{"events": []}],  # no turn_index
            },
        }]
    }
    errors = validate_trace_structure(dataset)
    assert any("missing 'turn_index'" in e for e in errors)


def test_validate_trace_structure_turn_missing_events():
    """Line 56: turn missing 'events' produces error."""
    from evals.harness import validate_trace_structure
    dataset = {
        "eval_cases": [{
            "eval_case_id": "c1",
            "agent_data": {
                "agents": {"a": {}},
                "turns": [{"turn_index": 0}],  # no events
            },
        }]
    }
    errors = validate_trace_structure(dataset)
    assert any("missing 'events'" in e for e in errors)


# ── validate_all_datasets ─────────────────────────────────────────────────────

def test_validate_all_datasets_passes_valid(tmp_path):
    from evals import harness
    data = {
        "eval_cases": [{
            "eval_case_id": "ok",
            "agent_data": {
                "agents": {"coord": {}},
                "turns": [{"turn_index": 0, "events": []}],
            },
        }]
    }
    (tmp_path / "valid.json").write_text(json.dumps(data))
    with patch.object(harness, "DATASETS_DIR", tmp_path):
        harness.validate_all_datasets()  # should not raise


def test_validate_all_datasets_raises_on_error(tmp_path):
    """Lines 66-67: AssertionError raised with helpful message."""
    import pytest

    from evals import harness
    bad = {"eval_cases": [{"eval_case_id": "bad_case"}]}  # missing prompt/agent_data
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with (
        patch.object(harness, "DATASETS_DIR", tmp_path),
        pytest.raises(AssertionError, match="structural errors"),
    ):
        harness.validate_all_datasets()


# ── extract_tool_call_sequence ────────────────────────────────────────────────

def test_extract_tool_call_sequence_empty():
    from evals.harness import extract_tool_call_sequence
    assert extract_tool_call_sequence([]) == []


def test_extract_tool_call_sequence_finds_calls():
    from evals.harness import extract_tool_call_sequence
    turns = [
        {
            "events": [
                {
                    "author": "coordinator",
                    "content": {
                        "parts": [
                            {"function_call": {"name": "write_trade", "args": {}}},
                        ]
                    },
                }
            ]
        },
        {
            "events": [
                {
                    "author": "coordinator",
                    "content": {
                        "parts": [
                            {"function_call": {"name": "place_market_order", "args": {}}},
                        ]
                    },
                }
            ]
        },
    ]
    calls = extract_tool_call_sequence(turns)
    assert calls == ["write_trade", "place_market_order"]


# ── check_write_ahead_invariant ───────────────────────────────────────────────

def test_check_write_ahead_invariant_no_order():
    from evals.harness import check_write_ahead_invariant
    turns = [
        {
            "events": [{
                "author": "coordinator",
                "content": {"parts": [{"function_call": {"name": "write_trade", "args": {}}}]},
            }]
        }
    ]
    assert check_write_ahead_invariant(turns) is True


def test_check_write_ahead_invariant_write_before_order():
    from evals.harness import check_write_ahead_invariant
    turns = [
        {
            "events": [
                {"author": "a", "content": {"parts": [{"function_call": {"name": "write_trade", "args": {}}}]}},
                {"author": "a", "content": {"parts": [{"function_call": {"name": "place_market_order", "args": {}}}]}},
            ]
        }
    ]
    assert check_write_ahead_invariant(turns) is True


def test_check_write_ahead_invariant_order_without_write():
    from evals.harness import check_write_ahead_invariant
    turns = [
        {
            "events": [
                {"author": "a", "content": {"parts": [{"function_call": {"name": "place_market_order", "args": {}}}]}},
            ]
        }
    ]
    assert check_write_ahead_invariant(turns) is False


# ── print_scenario_summary ────────────────────────────────────────────────────

def test_print_scenario_summary_runs_without_error(tmp_path, capsys):
    """Lines 99-112: print_scenario_summary prints table for each dataset."""
    from evals import harness
    data = {
        "eval_cases": [{
            "eval_case_id": "happy_path",
            "agent_data": {
                "agents": {"coordinator": {}},
                "turns": [
                    {
                        "turn_index": 0,
                        "events": [
                            {
                                "author": "coordinator",
                                "content": {"parts": [{"function_call": {"name": "write_trade", "args": {}}}]},
                            },
                            {
                                "author": "coordinator",
                                "content": {"parts": [{"text": "COMMITTED cycle 0"}]},
                            },
                        ],
                    }
                ],
            },
        }]
    }
    (tmp_path / "happy.json").write_text(json.dumps(data))
    with patch.object(harness, "DATASETS_DIR", tmp_path):
        harness.print_scenario_summary()
    out = capsys.readouterr().out
    assert "happy_path" in out


# ── __main__ ──────────────────────────────────────────────────────────────────

def test_main_block_validates_and_prints(tmp_path, capsys):
    """Lines 116-119: __main__ block validates datasets and calls print_scenario_summary."""
    from evals import harness
    data = {
        "eval_cases": [{
            "eval_case_id": "main_case",
            "agent_data": {
                "agents": {"coordinator": {}},
                "turns": [{"turn_index": 0, "events": []}],
            },
        }]
    }
    (tmp_path / "main.json").write_text(json.dumps(data))
    with (
        patch.object(harness, "DATASETS_DIR", tmp_path),
        patch.object(harness, "EVAL_CONFIG", tmp_path / "eval_config.yaml"),
    ):
        runpy.run_module("evals.harness", run_name="__main__", alter_sys=False)
    out = capsys.readouterr().out
    assert "valid" in out.lower() or "main_case" in out
