"""Tests for the eval harness utilities — no ADK, no external APIs."""

from pathlib import Path

from evals.harness import (
    check_write_ahead_invariant,
    extract_tool_call_sequence,
    list_datasets,
    load_dataset,
    validate_all_datasets,
    validate_trace_structure,
)

DATASETS_DIR = Path(__file__).parent.parent / "eval" / "datasets"


# ---------------------------------------------------------------------------
# validate_trace_structure
# ---------------------------------------------------------------------------


def test_valid_trace_passes():
    dataset = {
        "eval_cases": [
            {
                "eval_case_id": "test_case",
                "agent_data": {
                    "agents": {"coordinator": {"agent_id": "coordinator"}},
                    "turns": [
                        {
                            "turn_index": 0,
                            "events": [{"author": "user", "content": {}}],
                        }
                    ],
                },
            }
        ]
    }
    errors = validate_trace_structure(dataset)
    assert errors == []


def test_missing_agent_data_and_prompt():
    dataset = {"eval_cases": [{"eval_case_id": "bad"}]}
    errors = validate_trace_structure(dataset)
    assert any("bad" in e for e in errors)


def test_missing_agents_key():
    dataset = {
        "eval_cases": [
            {
                "eval_case_id": "no_agents",
                "agent_data": {"turns": [{"turn_index": 0, "events": []}]},
            }
        ]
    }
    errors = validate_trace_structure(dataset)
    assert any("agents" in e for e in errors)


def test_missing_turn_index():
    dataset = {
        "eval_cases": [
            {
                "eval_case_id": "no_idx",
                "agent_data": {
                    "agents": {},
                    "turns": [{"events": []}],  # missing turn_index
                },
            }
        ]
    }
    errors = validate_trace_structure(dataset)
    assert any("turn_index" in e for e in errors)


# ---------------------------------------------------------------------------
# extract_tool_call_sequence
# ---------------------------------------------------------------------------


def _make_turns(calls: list[str]) -> list[dict]:
    events = [
        {
            "author": "coordinator",
            "content": {"parts": [{"function_call": {"name": name, "args": {}}}]},
        }
        for name in calls
    ]
    return [{"turn_index": 0, "events": events}]


def test_extract_empty():
    assert extract_tool_call_sequence([]) == []


def test_extract_order_preserved():
    calls = ["check_loss_limit", "research_agent", "write_trade", "execution_agent"]
    turns = _make_turns(calls)
    assert extract_tool_call_sequence(turns) == calls


# ---------------------------------------------------------------------------
# check_write_ahead_invariant
# ---------------------------------------------------------------------------


def test_write_ahead_correct_order():
    turns = _make_turns(["write_trade", "place_market_order"])
    assert check_write_ahead_invariant(turns) is True


def test_write_ahead_violated():
    turns = _make_turns(["place_market_order", "write_trade"])
    assert check_write_ahead_invariant(turns) is False


def test_write_ahead_no_order():
    turns = _make_turns(["write_trade", "record_cycle"])
    assert check_write_ahead_invariant(turns) is True


def test_write_ahead_no_write_no_order():
    turns = _make_turns(["check_loss_limit", "research_agent"])
    assert check_write_ahead_invariant(turns) is True


def test_write_ahead_order_without_write():
    turns = _make_turns(["check_loss_limit", "place_limit_order"])
    assert check_write_ahead_invariant(turns) is False


# ---------------------------------------------------------------------------
# validate_all_datasets — integration over real fixture files
# ---------------------------------------------------------------------------


def test_all_fixtures_valid():
    """All dataset files in tests/eval/datasets/ must pass structural validation."""
    validate_all_datasets()


def test_committed_cycle_write_ahead():
    """The committed cycle fixture must have write_trade before execution_agent."""
    path = DATASETS_DIR / "01_committed_cycle.json"
    dataset = load_dataset(path)
    case = dataset["eval_cases"][0]
    turns = case["agent_data"]["turns"]
    assert check_write_ahead_invariant(turns), (
        "write_trade must precede execution_agent in 01_committed_cycle"
    )


def test_safety_write_ahead_fixture():
    """The write_ahead_before_order safety case must pass the invariant check."""
    path = DATASETS_DIR / "03_safety_constraints.json"
    dataset = load_dataset(path)
    wa_case = next(
        c for c in dataset["eval_cases"] if c["eval_case_id"] == "write_ahead_before_order"
    )
    turns = wa_case["agent_data"]["turns"]
    assert check_write_ahead_invariant(turns)


def test_dataset_files_exist():
    datasets = list_datasets()
    assert len(datasets) >= 3, f"Expected at least 3 dataset files, found {len(datasets)}"
