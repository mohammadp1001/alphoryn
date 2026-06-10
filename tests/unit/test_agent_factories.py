"""Unit tests for agent factory functions — create_*_agent, build_app, risk agents."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ── analysis_agent ────────────────────────────────────────────────────────────

def test_create_analysis_agent_returns_agent():
    from agent.analysis_agent import create_analysis_agent
    agent = create_analysis_agent()
    assert agent is not None
    assert agent.name == "analysis_agent"


# ── execution_agent ───────────────────────────────────────────────────────────

def test_create_execution_agent_returns_agent():
    from agent.execution_agent import create_execution_agent
    agent = create_execution_agent()
    assert agent is not None
    assert agent.name == "execution_agent"


# ── research_agent ────────────────────────────────────────────────────────────

def test_create_research_agent_returns_agent():
    from agent.research_agent import create_research_agent
    agent = create_research_agent()
    assert agent is not None
    assert agent.name == "research_agent"


# ── risk_agents ───────────────────────────────────────────────────────────────

def test_create_risk_optimist_returns_agent():
    from agent.risk_agents import create_risk_optimist
    agent = create_risk_optimist("No calibration data.")
    assert agent is not None
    assert agent.name == "risk_optimist"


def test_create_risk_pessimist_returns_agent():
    from agent.risk_agents import create_risk_pessimist
    agent = create_risk_pessimist("No calibration data.")
    assert agent is not None
    assert agent.name == "risk_pessimist"


def test_create_risk_debate_returns_sequential_agent():
    from agent.risk_agents import create_risk_debate
    debate = create_risk_debate("opt cal", "pess cal")
    assert debate is not None
    assert debate.name == "risk_debate"


def test_create_risk_debate_has_two_sub_agents():
    from agent.risk_agents import create_risk_debate
    debate = create_risk_debate("opt", "pess")
    assert len(debate.sub_agents) == 2


# ── coordinator ───────────────────────────────────────────────────────────────

def test_create_coordinator_returns_agent():
    from agent.coordinator import create_coordinator
    from models.session import SessionParams, PlanState
    from models.enums import Strategy, OperatingMode

    params = SessionParams(
        strategy=Strategy.MOMENTUM,
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe_days=3,
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )
    plan_state = PlanState(session_id="test-session-id", params=params)

    agent = create_coordinator(params, plan_state)
    assert agent is not None
    assert agent.name == "coordinator"


def test_build_app_returns_runner_tuple():
    from agent.coordinator import build_app
    from models.session import SessionParams
    from models.enums import Strategy, OperatingMode

    params = SessionParams(
        strategy=Strategy.SECTOR_ROTATION,
        mode=OperatingMode.FULL_AUTO,
        loss_limit_eur=1000.0,
        timeframe_days=1,
        shortlist_n=3,
        hitl_timeout_seconds=30,
        hitl_timeout_action="confirm",
    )

    runner, session_id, plan_state, session_service = build_app(params)

    assert runner is not None
    assert len(session_id) > 0
    assert plan_state is not None
    assert session_service is not None


def test_session_init_callback_sets_flag():
    """_session_init_callback should mark session as initialised."""
    from agent.coordinator import _session_init_callback
    from unittest.mock import MagicMock

    mock_context = MagicMock()
    mock_context.state = {}  # empty state dict

    with patch("db.schema.init_db"):
        asyncio.run(_session_init_callback(mock_context))

    assert mock_context.state["session_initialised"] is True


def test_session_init_callback_skips_reinitialisation():
    """Second call should not call init_db again."""
    from agent.coordinator import _session_init_callback

    mock_context = MagicMock()
    mock_context.state = {"session_initialised": True}  # already initialised

    with patch("db.schema.init_db") as mock_init:
        asyncio.run(_session_init_callback(mock_context))

    # init_db should not be called again
    mock_init.assert_not_called()
