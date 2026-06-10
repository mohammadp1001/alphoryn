"""Shared before/after agent callbacks for structured logging of sub-agent I/O."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]

from infra.rate_limiter import acquire_gemini

logger = logging.getLogger("agent.callbacks")

_MAX_CHARS = 2000


def _serialise(value: object) -> str:
    try:
        raw = json.dumps(value, indent=2, default=str)
    except Exception:
        raw = repr(value)
    if len(raw) > _MAX_CHARS:
        return raw[:_MAX_CHARS] + "\n  …(truncated)"
    return raw


def make_agent_log_callbacks(
    agent_name: str,
    output_key: str,
) -> tuple[Callable, Callable]:
    """Return (before_callback, after_callback) that rate-limit and log agent I/O."""

    async def before_callback(callback_context: CallbackContext) -> None:
        # Acquire a Gemini API token before the agent makes its first LLM call.
        # This is the primary defence against 429 RESOURCE_EXHAUSTED from Vertex AI.
        await acquire_gemini()

        request_text = "<unavailable>"
        try:
            content = callback_context.user_content
            if content and content.parts:
                request_text = " ".join(
                    p.text for p in content.parts if hasattr(p, "text") and p.text
                ) or "<empty>"
        except Exception:
            pass
        logger.debug(
            "AGENT ▶  %-20s  request = %s",
            agent_name,
            request_text,
        )

    async def after_callback(callback_context: CallbackContext) -> None:
        output = callback_context.state.get(output_key)
        if output is not None:
            logger.debug(
                "AGENT ◀  %-20s  %s =\n%s",
                agent_name,
                output_key,
                _serialise(output),
            )
        else:
            logger.warning(
                "AGENT ◀  %-20s  state key '%s' is EMPTY — output_schema enforcement may have failed",
                agent_name,
                output_key,
            )

    return before_callback, after_callback
