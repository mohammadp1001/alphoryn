"""Main agent for Alphoryn — LLM-based per-session trading decisions.

Google ADK LlmAgent wrapper that calls build_snapshot once and returns a
SessionDecision JSON. Constitution Principles I (no extra LLM calls) and V
(snapshot isolation) are enforced via the system prompt.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import types as genai_types

from alphoryn.agents.prompts import MAIN_AGENT_SYSTEM_PROMPT
from alphoryn.agents.responses import extract_response_json
from alphoryn.agents.thinking import thinking_enabled_config
from alphoryn.execution.agent import AssetDecision, SessionDecision
from alphoryn.market_data.client import MarketDataClient
from alphoryn.telemetry.logger import TelemetryLogger
from alphoryn.usage import TokenUsage, usage_from_event

_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_SKILL_NAMES = [
    "identify-regime",
    "mean-reversion-entry",
    "momentum-entry",
    "size-position",
    "read-memory",
]

_logger = logging.getLogger(__name__)


class MainAgentError(Exception):
    """Raised when the main agent fails to produce a valid SessionDecision."""


class MainAgent:
    """Wraps a Google ADK LlmAgent for per-candle trading decisions.

    build_snapshot is the sole registered ADK tool. The agent is invoked
    synchronously once per candle close and must return a JSON SessionDecision.
    """

    _MODEL = "gemini-2.5-pro"

    def __init__(
        self,
        market_data_client: MarketDataClient,
        logger: TelemetryLogger,
    ) -> None:
        self._logger = logger
        self.model = self._MODEL  # public: the scheduler prices usage against it
        self.usage = TokenUsage()  # accumulated across every decide() call
        skills = [load_skill_from_dir(_SKILLS_DIR / name) for name in _SKILL_NAMES]
        self._agent = LlmAgent(
            name="alphoryn_main_agent",
            model=self._MODEL,
            instruction=MAIN_AGENT_SYSTEM_PROMPT,
            tools=[market_data_client.build_snapshot, SkillToolset(skills)],
            generate_content_config=thinking_enabled_config(),
        )

    def decide(
        self,
        session_id: str,
        tickers: list[str],
        candle_close_at: datetime,
        memory_entries: list[dict[str, Any]] | None = None,
        session_money_budget: float | None = None,
    ) -> SessionDecision:
        """Run the LLM agent and return a SessionDecision.

        Emits TOOL_CALL, SIGNAL_SNAPSHOT_BUILT, and AGENT_DECISION telemetry.
        Raises MainAgentError if no valid JSON decision is produced.
        """
        t0 = datetime.now(UTC)
        prompt = _build_prompt(
            session_id, tickers, candle_close_at, memory_entries, session_money_budget
        )

        runner = InMemoryRunner(agent=self._agent, app_name="alphoryn")
        runner.auto_create_session = True

        raw_json: str | None = None
        session_usage = TokenUsage()
        for event in runner.run(
            user_id="system",
            session_id=session_id,
            new_message=genai_types.Content(
                parts=[genai_types.Part(text=prompt)],
                role="user",
            ),
        ):
            session_usage = session_usage + usage_from_event(event)
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
                raw_json = extract_response_json(event.content.parts)

        # Recorded before the failure paths below: a session that failed still
        # spent the tokens it spent. The 2026-08-13 run burned three retries on
        # a session that produced nothing, and that spend is exactly the kind
        # you want to see.
        self.usage = self.usage + session_usage
        self._logger.emit(
            "TOKEN_USAGE",
            "main_agent",
            {
                "model": self._MODEL,
                "calls": session_usage.calls,
                "input_tokens": session_usage.input_tokens,
                "cached_input_tokens": session_usage.cached_input_tokens,
                "output_tokens": session_usage.output_tokens,
                "reasoning_tokens": session_usage.reasoning_tokens,
                "estimated_usd": session_usage.estimated_usd(self._MODEL),
            },
            session_id=session_id,
        )

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
            {"decisions": {d.ticker: d.action for d in decision.decisions}},
            session_id=session_id,
            latency_ms=latency_ms,
        )
        return decision


def _build_prompt(
    session_id: str,
    tickers: list[str],
    candle_close_at: datetime,
    memory_entries: list[dict[str, Any]] | None,
    session_money_budget: float | None = None,
) -> str:
    lines = [
        f"session_id: {session_id}",
        f"tickers: {', '.join(tickers)}",
        f"candle_close_at: {candle_close_at.isoformat()}",
    ]
    if session_money_budget is not None:
        lines.append(f"session_money_budget: {session_money_budget}")
    if memory_entries:
        lines.append(f"memory_entries: {json.dumps(memory_entries)}")
    return "\n".join(lines)


def _parse_decision(data: dict[str, Any]) -> SessionDecision:
    """Parse the raw JSON dict from the LLM into a SessionDecision."""
    try:
        decisions = [AssetDecision(**d) for d in data["decisions"]]
        return SessionDecision(
            session_id=data["session_id"],
            decisions=decisions,
        )
    except (KeyError, TypeError) as exc:
        _logger.exception("Invalid SessionDecision structure from main_agent response: %s", exc)
        raise MainAgentError(f"Invalid SessionDecision structure: {exc}") from exc
