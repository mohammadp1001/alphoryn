"""Shared before/after agent callbacks for structured logging of sub-agent I/O."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

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
                request_text = (
                    " ".join(p.text for p in content.parts if hasattr(p, "text") and p.text)
                    or "<empty>"
                )
        except Exception:
            pass
        logger.info(
            "[%s] ▶  request=%s",
            agent_name,
            request_text,
            extra={"agent": agent_name, "event": "agent_start"},
        )

    async def after_callback(callback_context: CallbackContext) -> None:
        output = callback_context.state.get(output_key)
        if output is not None:
            logger.info(
                "[%s] ◀  output_key=%s",
                agent_name,
                output_key,
                extra={"agent": agent_name, "event": "agent_done", "output_key": output_key},
            )
            logger.debug(
                "[%s] ◀  output=\n%s",
                agent_name,
                _serialise(output),
                extra={"agent": agent_name, "event": "agent_output", "output_key": output_key},
            )
        else:
            logger.warning(
                "[%s] ◀  output_key=%s is EMPTY — output_schema enforcement may have failed",
                agent_name,
                output_key,
                extra={
                    "agent": agent_name,
                    "event": "agent_empty_output",
                    "output_key": output_key,
                },
            )

    return before_callback, after_callback


def make_research_file_callback(
    session_id: str,
    symbol: str,
    output_key: str,
) -> Callable:
    """Return an after-callback that writes the research agent output to a markdown file.

    Reads the agent text output from state[output_key], writes it to
    reports/{session_id}/research/{symbol}_{ts}.md, registers the file in
    session_files, and injects the path into state["research_report_path"].
    """

    async def after_callback(callback_context: CallbackContext) -> None:
        text = callback_context.state.get(output_key)
        if not text:
            logger.warning(
                "[research_agent] file_write  output_key=%s  status=empty",
                output_key,
                extra={
                    "agent": "research_agent",
                    "event": "file_write_skipped",
                    "output_key": output_key,
                },
            )
            return
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = Path("reports") / session_id / "research" / f"{symbol}_{ts}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text), encoding="utf-8")
        from db.schema import register_session_file as _register

        _register(session_id=session_id, path=str(path), file_type="research", symbol=symbol)
        callback_context.state["research_report_path"] = str(path)
        logger.info(
            "[research_agent] file_write  path=%s  symbol=%s",
            path,
            symbol,
            extra={
                "agent": "research_agent",
                "event": "file_write_done",
                "symbol": symbol,
                "path": str(path),
            },
        )

    return after_callback
