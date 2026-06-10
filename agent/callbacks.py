"""Shared before/after agent callbacks for structured logging of sub-agent I/O."""
from __future__ import annotations

import json
import logging
from typing import Callable

from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]

logger = logging.getLogger("agent.callbacks")


def _serialise(value: object) -> str:
    """Best-effort JSON serialisation — falls back to repr for non-serialisable types."""
    try:
        return json.dumps(value, indent=2, default=str)
    except Exception:
        return repr(value)


def make_agent_log_callbacks(
    agent_name: str,
    output_key: str,
) -> tuple[Callable, Callable]:
    """Return (before_callback, after_callback) that log agent I/O at INFO level.

    before_callback — logs the incoming user_content (the coordinator's request).
    after_callback  — logs the structured Pydantic output written to state[output_key].
    """

    async def before_callback(callback_context: CallbackContext) -> None:
        request_text = ""
        try:
            content = callback_context.user_content
            if content and content.parts:
                request_text = " ".join(
                    p.text for p in content.parts if hasattr(p, "text") and p.text
                )
        except Exception:
            request_text = "<unavailable>"
        logger.info("[%s] ▶ starting | request: %s", agent_name, request_text or "<empty>")

    async def after_callback(callback_context: CallbackContext) -> None:
        output = callback_context.state.get(output_key)
        if output is not None:
            logger.info(
                "[%s] ◀ completed | %s:\n%s",
                agent_name,
                output_key,
                _serialise(output),
            )
        else:
            logger.warning(
                "[%s] ◀ completed | state key '%s' is empty — output_schema may have failed",
                agent_name,
                output_key,
            )

    return before_callback, after_callback
