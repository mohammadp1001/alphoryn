"""Parallel debate agent factories — optimist and pessimist as independent AgentTools.

Each agent receives only the `read_file` tool so it can read the cycle HTML
report at the path passed in the coordinator's invocation message.
The coordinator invokes both agents in the same LLM turn (parallel tool calls)
and then calls synthesise_risk after receiving both verdicts.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from google.adk.agents import Agent  # type: ignore[import]
from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]
from google.adk.models.llm_response import LlmResponse  # type: ignore[import]
from google.adk.tools import FunctionTool  # type: ignore[import]

from agent.callbacks import make_agent_log_callbacks
from agent.prompts import RISK_OPTIMIST_INSTRUCTION, RISK_PESSIMIST_INSTRUCTION
from tools.file_tools import read_file
from tools.schemas import RiskVerdictOutput

logger = logging.getLogger("agent.debate_agents")

_OPTIMIST_MODEL = "openrouter/qwen/qwen-2.5-72b-instruct"
_PESSIMIST_MODEL = "openrouter/deepseek/deepseek-r1"

_JSON_BLOCK = re.compile(r"\{.*?\}", re.DOTALL)


def _lite_llm(model: str) -> object:
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    return LiteLlm(model=model)


def _make_json_validator_callback(model_cls: type[Any]):
    """Return an after_model_callback that validates JSON against model_cls."""

    async def _validate(
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        text = ""
        if llm_response.content and llm_response.content.parts:
            text = "".join(p.text or "" for p in llm_response.content.parts if hasattr(p, "text"))
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


def create_debate_optimist(
    calibration_summary: str,
    model: object = None,
) -> Agent:
    """Factory: returns a fresh optimist debate agent with read_file tool.

    The coordinator passes the HTML report path in the invocation message.
    The agent reads it, then returns a RiskVerdictOutput verdict.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
        model: Model ID. Default: Qwen2.5-72B via OpenRouter.
    """
    if model is None:
        model = _lite_llm(_OPTIMIST_MODEL)
    before_cb, after_cb = make_agent_log_callbacks("debate_optimist", "optimist_verdict")
    return Agent(
        name="debate_optimist",
        model=model,
        instruction=RISK_OPTIMIST_INSTRUCTION.format(calibration_summary=calibration_summary),
        tools=[FunctionTool(func=read_file)],
        description="Optimist debate agent — reads HTML report, argues for lowest justified risk.",
        output_key="optimist_verdict",
        output_schema=RiskVerdictOutput,
        before_agent_callback=before_cb,
        after_agent_callback=after_cb,
        after_model_callback=_make_json_validator_callback(RiskVerdictOutput),
    )


def create_debate_pessimist(
    calibration_summary: str,
    model: object = None,
) -> Agent:
    """Factory: returns a fresh pessimist debate agent with read_file tool.

    The coordinator passes the HTML report path in the invocation message.
    The agent reads it, then returns a RiskVerdictOutput verdict.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
        model: Model ID. Default: DeepSeek-R1 via OpenRouter.
    """
    if model is None:
        model = _lite_llm(_PESSIMIST_MODEL)
    before_cb, after_cb = make_agent_log_callbacks("debate_pessimist", "pessimist_verdict")
    return Agent(
        name="debate_pessimist",
        model=model,
        instruction=RISK_PESSIMIST_INSTRUCTION.format(calibration_summary=calibration_summary),
        tools=[FunctionTool(func=read_file)],
        description="Pessimist debate agent — reads HTML report, argues for highest justified risk.",
        output_key="pessimist_verdict",
        output_schema=RiskVerdictOutput,
        before_agent_callback=before_cb,
        after_agent_callback=after_cb,
        after_model_callback=_make_json_validator_callback(RiskVerdictOutput),
    )
