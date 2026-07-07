"""Feedback evaluation agent for Alphoryn.

Compares the original investment thesis (extracted from the session HTML report)
to the actual trade outcome and writes a FeedbackEvaluation record to the memory bank.

Retry policy: up to 3 attempts. On 3rd consecutive failure: writes a partial
FeedbackEvaluation, marks Position.status = EVALUATION_FAILED (which unblocks
the ticker for new BUYs), and emits warning telemetry.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from alphoryn.agents.prompts import FEEDBACK_AGENT_SYSTEM_PROMPT
from alphoryn.market_data.client import MarketDataClient
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import FeedbackEvaluation
from alphoryn.telemetry.logger import TelemetryLogger

_logger = logging.getLogger(__name__)

_FEEDBACK_AGENT_MODEL = "gemini-2.5-pro"
_MAX_ATTEMPTS = 3


def _pnl_pct(entry_price: float, exit_price: float) -> float:
    return (exit_price - entry_price) / entry_price * 100


@dataclass(frozen=True)
class FeedbackInput:
    """Data passed by the scheduler to the feedback agent for one closed position."""

    position_id: int
    session_id: str
    ticker: str
    strategy: Literal["MEAN_REVERSION", "MOMENTUM"]
    html_report_path: str
    entry_price: float
    exit_price: float
    exit_reason: str


class FeedbackAgentError(Exception):
    """Raised when the feedback agent cannot produce a valid evaluation."""


class FeedbackAgent:
    """LLM-powered feedback evaluation agent.

    Uses Google ADK LlmAgent with Gemini to compare the original trade thesis
    to the actual outcome and produce a CORRECT/INCORRECT/NEUTRAL judgment.
    """

    def __init__(
        self,
        market_data_client: MarketDataClient,
        bank: MemoryBank,
        logger: TelemetryLogger,
    ) -> None:
        self._market_data = market_data_client
        self._bank = bank
        self._logger = logger
        self._agent = LlmAgent(
            name="alphoryn_feedback_agent",
            model=_FEEDBACK_AGENT_MODEL,
            instruction=FEEDBACK_AGENT_SYSTEM_PROMPT,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def evaluate(self, feedback_input: FeedbackInput, current_session_id: str) -> None:
        """Evaluate a closed position and write a FeedbackEvaluation to the bank.

        Retries up to 3 times on LLM failure. On 3rd failure, writes
        EVALUATION_FAILED status and unblocks the ticker.
        """
        thesis = self._extract_thesis(feedback_input.html_report_path)
        current_price = self._market_data.get_latest_price(feedback_input.ticker)

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                raw_json = self._call_agent(feedback_input, thesis, current_price, attempt)
                result = self._parse_result(raw_json)
                self._write_success(
                    feedback_input,
                    current_session_id,
                    current_price,
                    thesis,
                    result,
                    attempt,
                )
                return
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS:
                    continue

        # All attempts exhausted
        self._write_failure(feedback_input, current_session_id, current_price, thesis)
        self._logger.emit(
            "EVALUATION_FAILED",
            "feedback_agent",
            {
                "position_id": feedback_input.position_id,
                "ticker": feedback_input.ticker,
                "error": str(last_exc),
            },
            session_id=current_session_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_thesis(html_report_path: str) -> str:
        """Read the HTML report and extract the investment-thesis section text."""
        with open(html_report_path, encoding="utf-8") as f:
            html = f.read()
        match = re.search(
            r'<section[^>]+id=["\']investment-thesis["\'][^>]*>(.*?)</section>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            raw = match.group(1)
            return re.sub(r"<[^>]+>", "", raw).strip()
        return html

    def _call_agent(
        self,
        feedback_input: FeedbackInput,
        thesis: str,
        current_price: float,
        attempt: int,
    ) -> str:
        """Invoke the LLM and return the raw JSON response string."""
        prompt = self._build_prompt(feedback_input, thesis, current_price)
        session_id = f"feedback-{feedback_input.position_id}-attempt-{attempt}"
        runner = InMemoryRunner(agent=self._agent, app_name="alphoryn_feedback")
        runner.auto_create_session = True

        self._logger.emit(
            "TOOL_CALL",
            "feedback_agent",
            {"attempt": attempt},
            session_id=session_id,
        )

        raw_json: str | None = None
        for event in runner.run(
            user_id="system",
            session_id=session_id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=prompt)],
            ),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                raw_json = event.content.parts[0].text

        if raw_json is None:
            _logger.error("feedback_agent produced no final response (attempt %d)", attempt)
            raise FeedbackAgentError("feedback_agent produced no final response")
        return raw_json

    @staticmethod
    def _build_prompt(
        feedback_input: FeedbackInput,
        thesis: str,
        current_price: float,
    ) -> str:
        pnl = _pnl_pct(feedback_input.entry_price, feedback_input.exit_price)
        return (
            f"POSITION FEEDBACK EVALUATION\n\n"
            f"Ticker: {feedback_input.ticker}\n"
            f"Strategy: {feedback_input.strategy}\n\n"
            f"INVESTMENT THESIS (extracted from entry session report):\n{thesis}\n\n"
            f"TRADE OUTCOME:\n"
            f"  Entry price: {feedback_input.entry_price:.2f}\n"
            f"  Exit price:  {feedback_input.exit_price:.2f}\n"
            f"  Exit reason: {feedback_input.exit_reason}\n"
            f"  P&L: {pnl:.2f}%\n\n"
            f"CURRENT CANDLE CLOSE PRICE: {current_price:.2f}\n\n"
            "Produce your JSON evaluation now."
        )

    @staticmethod
    def _parse_result(raw_json: str) -> dict:
        """Parse and validate the LLM JSON output."""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            _logger.exception("feedback_agent returned invalid JSON: %s", exc)
            raise FeedbackAgentError(f"Invalid JSON from feedback_agent: {exc}") from exc
        required = {"outcome_judgment", "thesis_summary", "reasoning"}
        missing = required - data.keys()
        if missing:
            _logger.error("feedback_agent response missing required fields: %s", missing)
            raise FeedbackAgentError(f"Missing fields in feedback response: {missing}")
        if data["outcome_judgment"] not in ("CORRECT", "INCORRECT", "NEUTRAL"):
            _logger.error(
                "feedback_agent returned invalid outcome_judgment: %r",
                data["outcome_judgment"],
            )
            raise FeedbackAgentError(
                f"Invalid outcome_judgment: {data['outcome_judgment']!r}"
            )
        return data

    def _write_success(
        self,
        feedback_input: FeedbackInput,
        current_session_id: str,
        current_price: float,
        thesis: str,
        result: dict,
        attempt: int,
    ) -> None:
        evaluation = FeedbackEvaluation(
            position_id=feedback_input.position_id,
            evaluated_at=datetime.now(UTC),
            evaluation_session_id=current_session_id,
            candle_close_price=current_price,
            thesis_summary=result["thesis_summary"],
            outcome_judgment=result["outcome_judgment"],
            reasoning=result["reasoning"],
            attempt_count=attempt,
        )
        self._bank.write_feedback_evaluation(evaluation, "EVALUATED")
        self._bank.update_memory_entry_judgment(
            session_id=feedback_input.session_id,
            ticker=feedback_input.ticker,
            strategy=feedback_input.strategy,
            outcome_judgment=result["outcome_judgment"],
        )
        self._logger.emit(
            "AGENT_DECISION",
            "feedback_agent",
            {
                "position_id": feedback_input.position_id,
                "ticker": feedback_input.ticker,
                "outcome_judgment": result["outcome_judgment"],
                "attempt": attempt,
            },
            session_id=current_session_id,
        )

    def _write_failure(
        self,
        feedback_input: FeedbackInput,
        current_session_id: str,
        current_price: float,
        thesis: str,
    ) -> None:
        evaluation = FeedbackEvaluation(
            position_id=feedback_input.position_id,
            evaluated_at=datetime.now(UTC),
            evaluation_session_id=current_session_id,
            candle_close_price=current_price,
            thesis_summary=thesis[:500] if thesis else "unavailable",
            outcome_judgment="NEUTRAL",
            reasoning="Evaluation failed after 3 attempts; judgment defaulted to NEUTRAL.",
            attempt_count=_MAX_ATTEMPTS,
        )
        self._bank.write_feedback_evaluation(evaluation, "EVALUATION_FAILED")
