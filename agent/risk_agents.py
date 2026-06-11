"""Risk debate agent factories — optimist and pessimist for SequentialAgent."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from google.adk.agents import Agent, SequentialAgent  # type: ignore[import]
from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]
from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]
from google.adk.models.llm_response import LlmResponse  # type: ignore[import]

from agent.callbacks import make_agent_log_callbacks
from agent.prompts import RISK_OPTIMIST_INSTRUCTION, RISK_PESSIMIST_INSTRUCTION
from tools.schemas import RiskVerdictOutput

logger = logging.getLogger("agent.risk_agents")

_OPENROUTER_OPTIMIST  = LiteLlm(model="openrouter/qwen/qwen-2.5-72b-instruct")
_OPENROUTER_PESSIMIST = LiteLlm(model="openrouter/deepseek/deepseek-chat")

_JSON_BLOCK = re.compile(r"\{.*?\}", re.DOTALL)


def _make_json_validator_callback(model_cls: type[Any]):
    """Return an after_model_callback that validates JSON against model_cls.

    Extracts the first JSON object from the raw response text, parses it,
    and validates the shape against model_cls. Logs a warning on failure
    but does not raise — ADK's own handling continues either way.
    """
    async def _validate(
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        text = ""
        if llm_response.content and llm_response.content.parts:
            text = "".join(
                p.text or "" for p in llm_response.content.parts if hasattr(p, "text")
            )
        if not text:
            return None
        match = _JSON_BLOCK.search(text)
        if not match:
            logger.warning("%s: no JSON block found in model response", model_cls.__name__)
            return None
        try:
            data = json.loads(match.group())
            model_cls(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("%s: JSON validation failed — %s", model_cls.__name__, exc)
        return None

    return _validate


def create_risk_optimist(
    calibration_summary: str,
    model: str | LiteLlm = _OPENROUTER_OPTIMIST,
) -> Agent:
    """Factory: returns a fresh optimist risk agent.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
        model: Model ID. Default: Qwen2.5-72B via OpenRouter.
    """
    before_cb, after_cb = make_agent_log_callbacks("risk_optimist", "optimist_verdict")
    return Agent(
        name="risk_optimist",
        model=model,
        instruction=RISK_OPTIMIST_INSTRUCTION.format(
            calibration_summary=calibration_summary
        ),
        tools=[],
        description="Argues for the lowest justifiable risk level for a trade candidate.",
        output_key="optimist_verdict",
        output_schema=RiskVerdictOutput,
        before_agent_callback=before_cb,
        after_agent_callback=after_cb,
        after_model_callback=_make_json_validator_callback(RiskVerdictOutput),
    )


def create_risk_pessimist(
    calibration_summary: str,
    model: str | LiteLlm = _OPENROUTER_PESSIMIST,
) -> Agent:
    """Factory: returns a fresh pessimist risk agent.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
        model: Model ID. Default: DeepSeek-V3 via OpenRouter.
    """
    before_cb, after_cb = make_agent_log_callbacks("risk_pessimist", "pessimist_verdict")
    return Agent(
        name="risk_pessimist",
        model=model,
        instruction=RISK_PESSIMIST_INSTRUCTION.format(
            calibration_summary=calibration_summary
        ),
        tools=[],
        description=(
            "Argues for the highest justifiable risk level for a trade candidate. "
            "Reads the optimist verdict from state key 'optimist_verdict'."
        ),
        output_key="pessimist_verdict",
        output_schema=RiskVerdictOutput,
        before_agent_callback=before_cb,
        after_agent_callback=after_cb,
        after_model_callback=_make_json_validator_callback(RiskVerdictOutput),
    )


def create_risk_debate(
    opt_calibration_summary: str,
    pess_calibration_summary: str,
    optimist_model: str | LiteLlm = _OPENROUTER_OPTIMIST,
    pessimist_model: str | LiteLlm = _OPENROUTER_PESSIMIST,
) -> SequentialAgent:
    """Factory: returns a SequentialAgent that runs optimist then pessimist.

    Optimist: Qwen2.5-72B via OpenRouter.
    Pessimist: DeepSeek-V3 via OpenRouter.
    Requires OPENROUTER_API_KEY in environment.

    The optimist writes its verdict to state['optimist_verdict'].
    The pessimist reads that and writes to state['pessimist_verdict'].
    The coordinator reads both keys after the debate completes.

    Args:
        opt_calibration_summary: Calibration text for optimist prompt.
        pess_calibration_summary: Calibration text for pessimist prompt.
        optimist_model: Model ID for the optimist agent.
        pessimist_model: Model ID for the pessimist agent.
    """
    optimist = create_risk_optimist(opt_calibration_summary, model=optimist_model)
    pessimist = create_risk_pessimist(pess_calibration_summary, model=pessimist_model)

    return SequentialAgent(
        name="risk_debate",
        sub_agents=[optimist, pessimist],
        description="Two-agent adversarial risk debate: optimist (Qwen2.5) then pessimist (DeepSeek-V3).",
    )
