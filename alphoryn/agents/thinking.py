"""Gemini thinking configuration, and how to read a response that has thoughts.

Gemini 2.5 models reason internally whether or not you ask, but the thought
summary is only returned when include_thoughts is set. Without it there is
nothing for OpenTelemetry to capture, so a trace shows what the agent decided
and never why.

Turning it on changes the shape of every response: the model's reasoning
arrives as extra text parts in the same content, flagged with thought=True and
placed *before* the answer. Any caller that reads parts[0].text, or the first
non-empty text part, would start parsing a thought summary as if it were the
answer. is_thought_part exists so every such caller skips them.
"""

from typing import Any

from google.genai import types as genai_types


def thinking_enabled_config() -> genai_types.GenerateContentConfig:
    """Return a GenerateContentConfig that asks Gemini for its thought summary."""
    return genai_types.GenerateContentConfig(
        thinking_config=genai_types.ThinkingConfig(include_thoughts=True),
    )


def is_thought_part(part: Any) -> bool:
    """True if this response part is reasoning rather than the model's answer.

    The comparison is `is True`, not a truthiness test. Gemini sets thought
    exactly True on a summary part and leaves it None everywhere else, so
    nothing is lost by being strict - and being strict is what keeps a test
    double or an attribute-generating stub from reporting every part as a
    thought and silently swallowing the model's actual answer.
    """
    return getattr(part, "thought", None) is True
