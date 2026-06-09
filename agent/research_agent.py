"""Research agent factory — market regime detection and macro intelligence."""
from __future__ import annotations

from google.adk.agents import Agent  # type: ignore[import]

from agent.prompts import RESEARCH_AGENT_INSTRUCTION
from tools.registry import MARKET_TOOLS, RESEARCH_TOOLS


def create_research_agent() -> Agent:
    """Factory: returns a fresh research agent instance with no parent."""
    return Agent(
        name="research_agent",
        model="gemini-2.5-flash",
        instruction=RESEARCH_AGENT_INSTRUCTION,
        tools=RESEARCH_TOOLS + [
            # Market tools needed: macro data uses yfinance; market status from alpaca
            t for t in MARKET_TOOLS if t.func.__name__ in (
                "get_market_status", "get_benchmark_return", "get_sector_map"
            )
        ],
        description=(
            "Gathers macro and market intelligence; detects market regime; "
            "returns a structured MarketRegimeSummary."
        ),
    )
