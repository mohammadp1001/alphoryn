"""Unit tests for agent factory functions."""

from __future__ import annotations

# ── execution_agent ───────────────────────────────────────────────────────────


def test_create_execution_agent_returns_agent():
    from agent.execution_agent import create_execution_agent

    agent = create_execution_agent()
    assert agent is not None
    assert agent.name == "execution_agent"


def test_execution_agent_is_base_agent():
    from google.adk.agents import BaseAgent  # type: ignore[import]

    from agent.execution_agent import create_execution_agent

    agent = create_execution_agent()
    assert isinstance(agent, BaseAgent)


def test_execution_agent_model_param_accepted():
    from agent.execution_agent import create_execution_agent

    agent = create_execution_agent(model="gemini-2.5-flash")
    assert agent is not None


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


def test_create_risk_optimist_default_model():
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.risk_agents import _OPENROUTER_OPTIMIST_MODEL, create_risk_optimist

    agent = create_risk_optimist("cal")
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == _OPENROUTER_OPTIMIST_MODEL


def test_create_risk_pessimist_default_model():
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.risk_agents import _OPENROUTER_PESSIMIST_MODEL, create_risk_pessimist

    agent = create_risk_pessimist("cal")
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == _OPENROUTER_PESSIMIST_MODEL


def test_risk_agents_use_different_models_by_default():
    from agent.risk_agents import create_risk_optimist, create_risk_pessimist

    opt = create_risk_optimist("cal")
    pess = create_risk_pessimist("cal")
    assert opt.model != pess.model


def test_create_risk_optimist_custom_model():
    from agent.risk_agents import create_risk_optimist

    agent = create_risk_optimist("cal", model="gemini-2.5-pro")
    assert agent.model == "gemini-2.5-pro"


def test_create_risk_debate_returns_sequential_agent():
    from agent.risk_agents import create_risk_debate

    debate = create_risk_debate("opt cal", "pess cal")
    assert debate is not None
    assert debate.name == "risk_debate"


def test_create_risk_debate_has_two_sub_agents():
    from agent.risk_agents import create_risk_debate

    debate = create_risk_debate("opt", "pess")
    assert len(debate.sub_agents) == 2


def test_create_risk_debate_custom_models():
    from agent.risk_agents import create_risk_debate

    debate = create_risk_debate(
        "opt", "pess", optimist_model="gemini-2.5-pro", pessimist_model="gemini-2.5-flash"
    )
    assert debate.sub_agents[0].model == "gemini-2.5-pro"
    assert debate.sub_agents[1].model == "gemini-2.5-flash"


# ── coordinator ───────────────────────────────────────────────────────────────


def test_create_coordinator_returns_agent():
    from agent.coordinator import create_coordinator
    from models.enums import OperatingMode
    from models.session import PlanState, SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )
    plan_state = PlanState(session_id="test-session-id", params=params)

    agent = create_coordinator(params, plan_state)
    assert agent is not None
    assert agent.name == "coordinator"


def test_coordinator_default_model_is_flash():
    from agent.coordinator import create_coordinator
    from models.enums import OperatingMode
    from models.session import PlanState, SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )
    plan_state = PlanState(session_id="test-session-id", params=params)
    agent = create_coordinator(params, plan_state)
    assert agent.model == "gemini-2.5-flash"


def test_coordinator_does_not_have_execution_tools():
    """Coordinator tool list must not include any execution__* tools."""
    from agent.coordinator import create_coordinator
    from models.enums import OperatingMode
    from models.session import PlanState, SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )
    plan_state = PlanState(session_id="test-session-id", params=params)
    agent = create_coordinator(params, plan_state)

    tool_names = [
        getattr(t, "name", None) or getattr(getattr(t, "func", None), "__name__", "")
        for t in agent.tools
    ]
    execution_tools = [n for n in tool_names if n.startswith("execution__")]
    assert execution_tools == [], f"Coordinator has execution tools: {execution_tools}"


def test_build_app_returns_runner_tuple():
    from agent.coordinator import build_app
    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.FULL_AUTO,
        loss_limit_eur=1000.0,
        timeframe="1Day",
        shortlist_n=3,
        hitl_timeout_seconds=30,
        hitl_timeout_action="confirm",
    )

    runner, session_id, plan_state, session_service = build_app(params)

    assert runner is not None
    assert len(session_id) > 0
    assert plan_state is not None
    assert session_service is not None


# ── coordinator: OpenRouter / _resolve_model ──────────────────────────────────


def test_resolve_model_none_returns_default():
    from agent.coordinator import _resolve_model

    assert _resolve_model(None) == "gemini-2.5-flash"


def test_resolve_model_gemini_string_passes_through():
    from agent.coordinator import _resolve_model

    assert _resolve_model("gemini-2.5-pro") == "gemini-2.5-pro"


def test_resolve_model_openrouter_returns_litellm():
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.coordinator import _resolve_model

    result = _resolve_model("openrouter/qwen/qwen-2.5-72b-instruct")
    assert isinstance(result, LiteLlm)


def test_coordinator_params_openrouter_model_uses_litellm():
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.coordinator import create_coordinator
    from models.enums import OperatingMode
    from models.session import PlanState, SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
        coordinator_model="openrouter/qwen/qwen-2.5-72b-instruct",
    )
    plan_state = PlanState(session_id="test-openrouter-coord", params=params)
    agent = create_coordinator(params, plan_state)
    assert isinstance(agent.model, LiteLlm)


def test_coordinator_params_gemini_model_passes_through():
    from agent.coordinator import create_coordinator
    from models.enums import OperatingMode
    from models.session import PlanState, SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
        coordinator_model="gemini-2.5-pro",
    )
    plan_state = PlanState(session_id="test-gemini-pro-coord", params=params)
    agent = create_coordinator(params, plan_state)
    assert agent.model == "gemini-2.5-pro"


def test_coordinator_explicit_model_arg_overrides_params():
    """Explicit model= kwarg wins over params.coordinator_model."""
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.coordinator import create_coordinator
    from models.enums import OperatingMode
    from models.session import PlanState, SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
        coordinator_model="gemini-2.5-flash",
    )
    plan_state = PlanState(session_id="test-explicit-model", params=params)
    explicit = LiteLlm(model="openrouter/qwen/qwen-2.5-72b-instruct")
    agent = create_coordinator(params, plan_state, model=explicit)
    assert agent.model == explicit
