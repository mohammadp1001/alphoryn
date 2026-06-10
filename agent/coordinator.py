"""
Coordinator agent — top-level orchestrator for the decision cycle.

Architecture:
  Coordinator (Agent with AgentTool subagents)
    ├── AgentTool(research_agent)   — market regime detection
    ├── AgentTool(analysis_agent)   — technical signal screening
    ├── AgentTool(risk_debate)      — SequentialAgent: optimist → pessimist
    └── AgentTool(execution_agent)  — order placement (credentials injected)

The coordinator also holds all memory.* and coordinator.* FunctionTools.

Factory pattern is required: calling create_coordinator() each time avoids the
"agent already has a parent" ADK error when running multiple sessions.
"""
from __future__ import annotations

import json
import os
from typing import Any

from google.adk.agents import Agent  # type: ignore[import]
from google.adk.agents.callback_context import CallbackContext  # type: ignore[import]
from google.adk.tools import AgentTool  # type: ignore[import]

from agent.analysis_agent import create_analysis_agent
from agent.execution_agent import create_execution_agent
from agent.prompts import COORDINATOR_INSTRUCTION
from agent.research_agent import create_research_agent
from agent.risk_agents import create_risk_debate
from models.session import SessionParams, PlanState
from tools.registry import ALL_COORDINATOR_TOOLS


def create_coordinator(params: SessionParams, plan_state: PlanState) -> Agent:
    """Factory: returns a fully wired coordinator agent for one session.

    Args:
        params: Session configuration (strategy, mode, limits, etc.).
        plan_state: Initial PlanState for this session.
    """
    # Calibration will be loaded at runtime inside the agent loop.
    # Use placeholder text until first calibration tool call.
    _placeholder_cal = "Calibration data will be loaded at the start of each cycle."

    research_tool = AgentTool(agent=create_research_agent())
    analysis_tool = AgentTool(agent=create_analysis_agent())
    risk_debate_tool = AgentTool(agent=create_risk_debate(_placeholder_cal, _placeholder_cal))
    execution_tool = AgentTool(agent=create_execution_agent())

    from config import ETF_UNIVERSES, DEFAULT_ETF_UNIVERSE
    universe_symbols = ETF_UNIVERSES.get(params.universe, DEFAULT_ETF_UNIVERSE)
    symbols_str = ", ".join(universe_symbols)

    instruction = COORDINATOR_INSTRUCTION.format(
        session_id=plan_state.session_id,
        strategy=params.strategy.value,
        mode=params.mode.value,
        loss_limit_eur=params.loss_limit_eur,
        shortlist_n=params.shortlist_n,
        hitl_timeout_seconds=params.hitl_timeout_seconds,
        hitl_timeout_action=params.hitl_timeout_action,
        universe=params.universe,
        symbols=symbols_str,
    )

    return Agent(
        name="coordinator",
        model="gemini-2.5-pro",
        instruction=instruction,
        tools=[
            research_tool,
            analysis_tool,
            risk_debate_tool,
            execution_tool,
            *ALL_COORDINATOR_TOOLS,
        ],
        before_agent_callback=_session_init_callback,
        description="Top-level coordinator; orchestrates the full ETF trading decision cycle.",
    )


async def _session_init_callback(callback_context: CallbackContext) -> None:
    """Initialise session state and resolve any outstanding unresolved trades."""
    state = callback_context.state

    # Persist the plan state into ADK session state on first invocation
    if "session_initialised" not in state:
        from db.schema import init_db
        init_db()
        state["session_initialised"] = True


def build_app(params: SessionParams) -> Any:
    """Build an ADK Runner App for one trading session.

    Returns (runner, session_id, plan_state, session_service).
    Caller must await session_service.create_session(...) before run_async().
    """
    import uuid
    from google.adk.runners import Runner  # type: ignore[import]
    from google.adk.sessions import InMemorySessionService  # type: ignore[import]

    session_id = str(uuid.uuid4())
    plan_state = PlanState(
        session_id=session_id,
        params=params,
    )

    coordinator = create_coordinator(params, plan_state)
    session_service = InMemorySessionService()

    runner = Runner(
        agent=coordinator,
        app_name="alphoryn",
        session_service=session_service,
    )
    return runner, session_id, plan_state, session_service
