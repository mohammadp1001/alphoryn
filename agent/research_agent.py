"""Research agent factory — text and sentiment analysis via get_news + read_file."""

from __future__ import annotations

import logging

from google.adk.agents import Agent  # type: ignore[import]
from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]
from google.adk.tools import FunctionTool  # type: ignore[import]

from agent.callbacks import make_agent_log_callbacks, make_research_file_callback
from agent.prompts import RESEARCH_AGENT_INSTRUCTION
from tools.file_tools import read_file
from tools.news import get_news

logger = logging.getLogger("agent.research_agent")

_DEFAULT_RESEARCH_MODEL = "openrouter/google/gemma-4-31b-it:free"
_RESEARCH_OUTPUT_KEY = "research_output"


def _lite_llm(model: str) -> object:
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    return LiteLlm(model=model)


def create_research_agent(
    session_id: str,
    symbol: str,
    model: object = None,
) -> Agent:
    """Factory: returns a fresh research agent for one symbol.

    Args:
        session_id: Active session UUID — used by the file-write after-callback.
        symbol: ETF ticker the agent will research — used in the output file name.
        model: LLM to use. Default: openrouter/google/gemma-4-31b-it:free via LiteLlm.
    """
    if model is None:
        model = _lite_llm(_DEFAULT_RESEARCH_MODEL)

    before_cb, log_after_cb = make_agent_log_callbacks("research_agent", _RESEARCH_OUTPUT_KEY)
    file_after_cb = make_research_file_callback(session_id, symbol, _RESEARCH_OUTPUT_KEY)

    async def after_cb(callback_context: CallbackContext) -> None:
        await log_after_cb(callback_context)
        await file_after_cb(callback_context)

    return Agent(
        name="research_agent",
        model=model,
        instruction=RESEARCH_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=get_news), FunctionTool(func=read_file)],
        description="Text and sentiment research agent — news and document reading only.",
        output_key=_RESEARCH_OUTPUT_KEY,
        before_agent_callback=before_cb,
        after_agent_callback=after_cb,
    )
