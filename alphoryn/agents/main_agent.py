"""Main agent for Alphoryn — LLM-based per-session trading decisions.

Google ADK LlmAgent wrapper that calls build_snapshot once and returns a
SessionDecision JSON. Constitution Principles I (no extra LLM calls) and V
(snapshot isolation) are enforced via the system prompt.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from alphoryn.agents.prompts import MAIN_AGENT_SYSTEM_PROMPT
from alphoryn.execution.agent import ETFDecision, SessionDecision
from alphoryn.market_data.client import MarketDataClient
from alphoryn.telemetry.logger import TelemetryLogger

_logger = logging.getLogger(__name__)


class MainAgentError(Exception):
    """Raised when the main agent fails to produce a valid SessionDecision."""


class MainAgent:
    """Wraps a Google ADK LlmAgent for per-candle trading decisions.

    build_snapshot is the sole registered ADK tool. The agent is invoked
    synchronously once per candle close and must return a JSON SessionDecision.
    """

    _MODEL = "gemini-2.0-flash"

    def __init__(
        self,
        market_data_client: MarketDataClient,
        logger: TelemetryLogger,
    ) -> None:
        self._logger = logger
        self._agent = LlmAgent(
            name="alphoryn_main_agent",
            model=self._MODEL,
            instruction=MAIN_AGENT_SYSTEM_PROMPT,
            tools=[market_data_client.build_snapshot],
        )

    def decide(
        self,
        session_id: str,
        etf1: str,
        etf2: str,
        candle_close_at: datetime,
        memory_entries: list[dict[str, Any]] | None = None,
    ) -> SessionDecision:
        """Run the LLM agent and return a SessionDecision.

        Emits TOOL_CALL, SIGNAL_SNAPSHOT_BUILT, and AGENT_DECISION telemetry.
        Raises MainAgentError if no valid JSON decision is produced.
        """
        t0 = datetime.now(UTC)
        prompt = _build_prompt(session_id, etf1, etf2, candle_close_at, memory_entries)

        runner = InMemoryRunner(agent=self._agent, app_name="alphoryn")
        runner._get_or_create_session(user_id="system", session_id=session_id)

        raw_json: str | None = None
        for event in runner.run(
            user_id="system",
            session_id=session_id,
            new_message=genai_types.Content(
                parts=[genai_types.Part(text=prompt)],
                role="user",
            ),
        ):
            for fc in event.get_function_calls():
                self._logger.emit(
                    "TOOL_CALL",
                    "main_agent",
                    {"tool": fc.name, "args": fc.args},
                    session_id=session_id,
                )
            for fr in event.get_function_responses():
                if fr.name == "build_snapshot":
                    self._logger.emit(
                        "SIGNAL_SNAPSHOT_BUILT",
                        "main_agent",
                        {"snapshot": str(fr.response)},
                        session_id=session_id,
                    )
            if event.is_final_response() and event.content and event.content.parts:
                raw_json = event.content.parts[0].text

        if raw_json is None:
            _logger.error("main_agent produced no final response for session %s", session_id)
            raise MainAgentError("main_agent produced no final response")

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            _logger.exception(
                "main_agent response for session %s is not valid JSON: %s", session_id, exc
            )
            raise MainAgentError(
                f"main_agent response is not valid JSON: {exc}"
            ) from exc

        decision = _parse_decision(data)
        latency_ms = int((datetime.now(UTC) - t0).total_seconds() * 1000)
        self._logger.emit(
            "AGENT_DECISION",
            "main_agent",
            {
                "etf1_action": decision.etf1.action,
                "etf2_action": decision.etf2.action,
            },
            session_id=session_id,
            latency_ms=latency_ms,
        )
        return decision


def _build_prompt(
    session_id: str,
    etf1: str,
    etf2: str,
    candle_close_at: datetime,
    memory_entries: list[dict[str, Any]] | None,
) -> str:
    lines = [
        f"session_id: {session_id}",
        f"etf1: {etf1}",
        f"etf2: {etf2}",
        f"candle_close_at: {candle_close_at.isoformat()}",
    ]
    if memory_entries:
        lines.append(f"memory_entries: {json.dumps(memory_entries)}")
    return "\n".join(lines)


def _parse_decision(data: dict[str, Any]) -> SessionDecision:
    """Parse the raw JSON dict from the LLM into a SessionDecision."""
    try:
        return SessionDecision(
            session_id=data["session_id"],
            etf1=ETFDecision(**data["etf1"]),
            etf2=ETFDecision(**data["etf2"]),
        )
    except (KeyError, TypeError) as exc:
        _logger.exception("Invalid SessionDecision structure from main_agent response: %s", exc)
        raise MainAgentError(f"Invalid SessionDecision structure: {exc}") from exc
