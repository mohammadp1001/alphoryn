"""Research agent factory — market regime detection and macro intelligence."""
from __future__ import annotations

from google.adk.agents import Agent  # type: ignore[import]

from agent.callbacks import make_agent_log_callbacks
from agent.prompts import RESEARCH_AGENT_INSTRUCTION
from tools.registry import MARKET_TOOLS, RESEARCH_TOOLS
from tools.schemas import MarketRegimeOutput


def create_research_agent() -> Agent:
    """Factory: returns a fresh research agent instance with no parent."""
    before_cb, after_cb = make_agent_log_callbacks("research_agent", "market_regime")
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
            "returns a structured MarketRegimeOutput."
        ),
        output_key="market_regime",
        output_schema=MarketRegimeOutput,
        before_agent_callback=before_cb,
        after_agent_callback=after_cb,
    )
