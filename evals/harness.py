"""
Eval harness — utilities for running alphoryn eval scenarios locally
without the agents-cli infrastructure.

Use this when:
  - agents-cli is not installed
  - You want to validate trace fixtures structurally before grading
  - You want to run the custom metric prompt_templates as a quick sanity check

Full eval (generate + grade) requires:
  pip install google-adk
  agents-cli eval run
"""
from __future__ import annotations

import json
from pathlib import Path

DATASETS_DIR = Path(__file__).parent.parent / "tests" / "eval" / "datasets"
EVAL_CONFIG = Path(__file__).parent.parent / "tests" / "eval" / "eval_config.yaml"


def load_dataset(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def list_datasets() -> list[Path]:
    return sorted(DATASETS_DIR.glob("*.json"))


def validate_trace_structure(dataset: dict) -> list[str]:
    """Check that trace cases have required fields for eval grade.

    Returns a list of error strings (empty if all valid).
    """
    errors = []
    for case in dataset.get("eval_cases", []):
        cid = case.get("eval_case_id", "<unknown>")
        if "agent_data" not in case and "prompt" not in case:
            errors.append(f"{cid}: missing both 'agent_data' and 'prompt'")
            continue

        ad = case.get("agent_data")
        if ad:
            if "agents" not in ad:
                errors.append(f"{cid}: agent_data missing 'agents'")
            if "turns" not in ad:
                errors.append(f"{cid}: agent_data missing 'turns'")
            else:
                for i, turn in enumerate(ad["turns"]):
                    if "turn_index" not in turn:
                        errors.append(f"{cid}: turn {i} missing 'turn_index'")
                    if "events" not in turn:
                        errors.append(f"{cid}: turn {i} missing 'events'")
    return errors


def validate_all_datasets() -> None:
    """Validate all dataset files; raise AssertionError on any structural error."""
    for path in list_datasets():
        dataset = load_dataset(path)
        errors = validate_trace_structure(dataset)
        if errors:
            msg = f"Dataset {path.name} has structural errors:\n" + "\n".join(f"  - {e}" for e in errors)
            raise AssertionError(msg)
        case_ids = [c["eval_case_id"] for c in dataset.get("eval_cases", [])]
        print(f"  {path.name}: {len(case_ids)} case(s) — {case_ids}")


def extract_tool_call_sequence(turns: list[dict]) -> list[str]:
    """Extract ordered list of tool names called by coordinator in a trace."""
    calls = []
    for turn in turns:
        for event in turn.get("events", []):
            for part in event.get("content", {}).get("parts", []):
                if "function_call" in part:
                    calls.append(part["function_call"]["name"])
    return calls


def check_write_ahead_invariant(turns: list[dict]) -> bool:
    """Return True if write_trade appears before any place_*_order call."""
    calls = extract_tool_call_sequence(turns)
    order_tools = {"place_market_order", "place_limit_order"}
    write_idx = next((i for i, c in enumerate(calls) if c == "write_trade"), None)
    order_idx = next((i for i, c in enumerate(calls) if c in order_tools), None)

    if order_idx is None:
        return True  # no order placed — invariant holds vacuously
    if write_idx is None:
        return False  # order placed but no write-ahead
    return write_idx < order_idx


def print_scenario_summary() -> None:
    """Print a summary table of all eval scenarios."""
    print("\nAlphoryn Eval Scenarios\n" + "=" * 60)
    for path in list_datasets():
        dataset = load_dataset(path)
        print(f"\n{path.stem}")
        for case in dataset.get("eval_cases", []):
            cid = case["eval_case_id"]
            turns = case.get("agent_data", {}).get("turns", [])
            calls = extract_tool_call_sequence(turns)
            wa_ok = check_write_ahead_invariant(turns)
            has_commit = any("COMMITTED" in str(e) for t in turns for e in t.get("events", []))
            has_abort = any("ABORTED" in str(e) for t in turns for e in t.get("events", []))
            outcome = "COMMITTED" if has_commit else ("ABORTED" if has_abort else "unknown")
            wa_str = "write-ahead OK" if wa_ok else "WRITE-AHEAD VIOLATION"
            print(f"  [{outcome:10s}] {cid} — {len(calls)} tool calls — {wa_str}")


if __name__ == "__main__":
    print("Validating datasets...")
    validate_all_datasets()
    print_scenario_summary()
    print("\nAll datasets valid.")
