"""Reading a JSON answer out of a Gemini response.

Every agent here asks the model for JSON and gets back a list of parts that
needs the same three things done to it: skip the thought summaries, skip the
parts that carry no text, and strip the markdown fences the model wraps its
answer in. Miss any one and `json.loads` fails at character 0.

This module exists because that logic was written twice - once in main_agent
and once in feedback_agent - and the two copies drifted. feedback_agent's copy
skipped thoughts but did neither of the other two, so it could never parse a
real reply: on 2026-08-11 it discarded a complete, correct evaluation three
times and filed the position as EVALUATION_FAILED, which is precisely what
FR-016a exists to prevent. One reader, used by both, cannot drift again.
"""

from collections.abc import Iterable
from typing import Any

from alphoryn.agents.thinking import is_thought_part


def strip_fences(text: str) -> str:
    """Strip markdown code fences from LLM output (e.g. ```json ... ```).

    Only a fence at the very start counts. Text that merely contains backticks
    - a JSON string value, say - is returned untouched.
    """
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening ```json / ``` line, and the closing ``` if there is one.
    inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
    return "\n".join(inner).strip()


def extract_response_json(parts: Iterable[Any]) -> str | None:
    """Return the first part that holds the model's answer, fences removed.

    Returns None when no part carries usable text, which callers treat as
    "the model produced no final response" rather than as an empty answer.
    """
    for part in parts:
        if is_thought_part(part):
            continue
        text = getattr(part, "text", None)
        if text and text.strip():
            return strip_fences(text.strip())
    return None
