"""Unit tests for alphoryn/agents/thinking.py."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from google.genai import types as genai_types

from alphoryn.agents.thinking import is_thought_part, thinking_enabled_config


def test_thinking_enabled_config_asks_for_thought_summaries() -> None:
    """Without include_thoughts the API returns no reasoning at all, so there
    is nothing for OpenTelemetry to capture."""
    config = thinking_enabled_config()
    assert config.thinking_config.include_thoughts is True


def test_thinking_enabled_config_returns_a_genai_config() -> None:
    assert isinstance(thinking_enabled_config(), genai_types.GenerateContentConfig)


def test_is_thought_part_true_for_a_thought_summary() -> None:
    assert is_thought_part(genai_types.Part(text="Let me weigh ADX...", thought=True)) is True


def test_is_thought_part_false_for_an_answer_part() -> None:
    assert is_thought_part(genai_types.Part(text='{"decisions": []}')) is False


def test_is_thought_part_false_when_thought_is_none() -> None:
    assert is_thought_part(SimpleNamespace(text="answer", thought=None)) is False


def test_is_thought_part_false_when_the_attribute_is_absent() -> None:
    assert is_thought_part(SimpleNamespace(text="answer")) is False


def test_is_thought_part_false_for_an_attribute_generating_stub() -> None:
    """A MagicMock hands back a truthy child for any attribute. A truthiness
    test would call every part a thought and swallow the model's answer."""
    assert is_thought_part(MagicMock()) is False
