"""Unit tests for _make_json_validator_callback in agent.risk_agents."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from tools.schemas import RiskVerdictOutput


def _make_llm_response(text: str | None):
    """Build a minimal mock LlmResponse with the given text content."""
    part = MagicMock()
    part.text = text
    content = MagicMock()
    content.parts = [part] if text is not None else []
    response = MagicMock()
    response.content = content
    return response


def _make_empty_llm_response():
    response = MagicMock()
    response.content = None
    return response


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def validator():
    from agent.risk_agents import _make_json_validator_callback
    return _make_json_validator_callback(RiskVerdictOutput)


@pytest.fixture()
def callback_context():
    return MagicMock()


def test_valid_json_returns_none(validator, callback_context):
    payload = json.dumps({
        "recommended_level": "LOW",
        "reasoning": "stable conditions",
        "acknowledged_opposing_signal": "minor volatility",
    })
    result = _run(validator(callback_context, _make_llm_response(payload)))
    assert result is None


def test_valid_json_embedded_in_text_returns_none(validator, callback_context):
    payload = (
        'Here is my verdict: '
        + json.dumps({
            "recommended_level": "MEDIUM",
            "reasoning": "mixed signals",
            "acknowledged_opposing_signal": "none",
        })
        + " end."
    )
    result = _run(validator(callback_context, _make_llm_response(payload)))
    assert result is None


def test_malformed_json_returns_none(validator, callback_context):
    result = _run(validator(callback_context, _make_llm_response("{bad json here")))
    assert result is None


def test_missing_required_field_logs_warning_returns_none(validator, callback_context):
    payload = json.dumps({"recommended_level": "HIGH"})
    result = _run(validator(callback_context, _make_llm_response(payload)))
    assert result is None


def test_no_json_block_returns_none(validator, callback_context):
    result = _run(validator(callback_context, _make_llm_response("No JSON here at all.")))
    assert result is None


def test_empty_text_returns_none(validator, callback_context):
    result = _run(validator(callback_context, _make_llm_response("")))
    assert result is None


def test_none_content_returns_none(validator, callback_context):
    result = _run(validator(callback_context, _make_empty_llm_response()))
    assert result is None


def test_empty_parts_returns_none(validator, callback_context):
    response = _make_llm_response(None)
    result = _run(validator(callback_context, response))
    assert result is None


def test_validator_does_not_raise_on_any_input(validator, callback_context):
    for text in [None, "", "garbage", "{}", '{"recommended_level": "LOW"}']:
        response = _make_empty_llm_response() if text is None else _make_llm_response(text)
        _run(validator(callback_context, response))
