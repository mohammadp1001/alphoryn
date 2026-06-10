"""Analysis agent factory — technical screening and signal ranking."""
from __future__ import annotations

from google.adk.agents import Agent  # type: ignore[import]

from agent.prompts import ANALYSIS_AGENT_INSTRUCTION
from tools.registry import ANALYSIS_TOOLS, MARKET_TOOLS
from tools.schemas import RankedSignalsOutput


def create_analysis_agent() -> Agent:
    """Factory: returns a fresh analysis agent instance with no parent."""
    return Agent(
        name="analysis_agent",
        model="gemini-2.5-flash",
        instruction=ANALYSIS_AGENT_INSTRUCTION,
        tools=MARKET_TOOLS + ANALYSIS_TOOLS,
        description=(
            "Screens the ETF universe for technical signals; computes RSI/MACD/Bollinger; "
            "runs signal lookback; returns ALL symbols ranked by score."
        ),
        output_key="ranked_signals",
        output_schema=RankedSignalsOutput,
    )
