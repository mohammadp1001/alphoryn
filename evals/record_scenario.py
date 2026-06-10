"""
Record a live coordinator run as an eval fixture.

Usage:
    python -m evals.record_scenario --session-id <sid> --output tests/eval/datasets/new_case.json

What it does:
1. Reads the session's events from the ADK InMemorySessionService
2. Converts events → eval grading-input trace format
3. Writes the result as a single-case EvaluationDataset JSON file

The output can be fed directly to `agents-cli eval grade` without running
`eval generate` first.

Pre-requisites:
    - The session was run with build_app() from agent/coordinator.py
    - The runner + session_id are accessible (run in the same process, or pass
      a previously serialised session file with --events-file)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _content_to_dict(content: Any) -> dict:
    """Convert ADK Content object to the trace dict format."""
    if content is None:
        return {}
    if isinstance(content, dict):
        return content
    # ADK Content has .parts; each Part has .text, .function_call, .function_response
    parts = []
    for part in getattr(content, "parts", []):
        p: dict = {}
        if hasattr(part, "text") and part.text:
            p["text"] = part.text
        if hasattr(part, "function_call") and part.function_call:
            fc = part.function_call
            p["function_call"] = {
                "name": fc.name,
                "args": dict(fc.args) if fc.args else {},
            }
        if hasattr(part, "function_response") and part.function_response:
            fr = part.function_response
            p["function_response"] = {
                "name": fr.name,
                "response": fr.response,
            }
        if p:
            parts.append(p)
    return {"parts": parts}


def events_to_trace(
    session_id: str,
    events: list[Any],
    agent_id: str = "coordinator",
    agent_instruction: str = "",
) -> dict:
    """Convert a flat list of ADK events to a grading-input trace dict."""
    current_turn: list[dict] = []
    current_turn_index = 0

    turns = []

    for event in events:
        author = getattr(event, "author", "unknown")
        content = _content_to_dict(getattr(event, "content", None))

        entry = {"author": author, "content": content}

        # New turn starts when user speaks after we've already collected something
        if author == "user" and current_turn:
            turns.append({"turn_index": current_turn_index, "events": current_turn})
            current_turn_index += 1
            current_turn = []

        current_turn.append(entry)

    if current_turn:
        turns.append({"turn_index": current_turn_index, "events": current_turn})

    return {
        "agents": {
            agent_id: {
                "agent_id": agent_id,
                "instruction": agent_instruction,
            }
        },
        "turns": turns,
    }


def record_from_runner(
    runner: Any,
    session_id: str,
    case_id: str,
    agent_instruction: str = "",
    output_path: Path | None = None,
) -> dict:
    """Record a session from a live Runner into an eval dataset dict.

    Args:
        runner: The ADK Runner instance used to run the session.
        session_id: The session ID to record.
        case_id: The eval_case_id for this fixture.
        agent_instruction: The coordinator instruction text (for the agents dict).
        output_path: If provided, write the dataset to this JSON file.

    Returns:
        The EvaluationDataset dict with one eval case.
    """
    service = runner.session_service
    session = service.get_session(
        app_name=runner.app_name,
        user_id="default",
        session_id=session_id,
    )
    if session is None:
        raise ValueError(f"Session {session_id!r} not found")

    events = list(session.events)
    agent_data = events_to_trace(
        session_id=session_id,
        events=events,
        agent_instruction=agent_instruction,
    )

    dataset = {
        "eval_cases": [
            {
                "eval_case_id": case_id,
                "agent_data": agent_data,
            }
        ]
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(dataset, f, indent=2)
        print(f"Wrote fixture: {output_path}")

    return dataset


def record_from_events_file(
    events_file: Path,
    case_id: str,
    session_id: str = "recorded",
    agent_instruction: str = "",
    output_path: Path | None = None,
) -> dict:
    """Record from a JSONL file of serialised ADK events.

    Each line is a JSON object with {author, content} fields.
    """
    events = []
    with open(events_file) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    # Convert dicts to simple objects with attributes
    class _E:
        def __init__(self, d: dict):
            self.author = d.get("author", "unknown")
            self.content = d.get("content", {})

    event_objs = [_E(e) for e in events]
    agent_data = events_to_trace(
        session_id=session_id,
        events=event_objs,
        agent_instruction=agent_instruction,
    )

    dataset = {
        "eval_cases": [
            {
                "eval_case_id": case_id,
                "agent_data": agent_data,
            }
        ]
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(dataset, f, indent=2)
        print(f"Wrote fixture: {output_path}")

    return dataset


def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Record a coordinator session as an eval fixture"
    )
    parser.add_argument("--case-id", required=True, help="eval_case_id for the fixture")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument(
        "--events-file",
        help="JSONL file with serialised events (one JSON object per line)",
    )
    parser.add_argument(
        "--session-id",
        default="recorded",
        help="Session ID (used in events_to_trace; label only for --events-file)",
    )
    parser.add_argument(
        "--instruction",
        default="",
        help="Coordinator instruction string for the agents dict",
    )
    args = parser.parse_args(argv)

    if not args.events_file:
        print("Error: --events-file is required for CLI usage.", file=sys.stderr)
        print(
            "To record from a live Runner, import record_from_runner() directly.",
            file=sys.stderr,
        )
        sys.exit(1)

    record_from_events_file(
        events_file=Path(args.events_file),
        case_id=args.case_id,
        session_id=args.session_id,
        agent_instruction=args.instruction,
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    _main()
