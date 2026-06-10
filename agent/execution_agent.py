"""Execution agent factory — order placement on Alpaca paper trading."""
from __future__ import annotations

from google.adk.agents import Agent  # type: ignore[import]

from agent.prompts import EXECUTION_AGENT_INSTRUCTION
from tools.registry import EXECUTION_TOOLS
from tools.schemas import OrderResultOutput


def create_execution_agent() -> Agent:
    """Factory: returns a fresh execution agent instance.

    Credentials are injected as environment variables by the coordinator harness
    immediately before this agent is invoked. The agent reads them from env only.
    """
    return Agent(
        name="execution_agent",
        model="gemini-2.5-flash",
        instruction=EXECUTION_AGENT_INSTRUCTION,
        tools=EXECUTION_TOOLS,
        description=(
            "Executes a single approved ETF trade on Alpaca paper account; "
            "returns a structured OrderResultOutput."
        ),
        output_key="order_result",
        output_schema=OrderResultOutput,
    )
