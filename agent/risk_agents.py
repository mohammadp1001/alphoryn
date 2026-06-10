"""Risk debate agent factories — optimist and pessimist for SequentialAgent."""
from __future__ import annotations

from google.adk.agents import Agent, SequentialAgent  # type: ignore[import]

from agent.callbacks import make_agent_log_callbacks
from agent.prompts import RISK_OPTIMIST_INSTRUCTION, RISK_PESSIMIST_INSTRUCTION
from tools.schemas import RiskVerdictOutput


def create_risk_optimist(
    calibration_summary: str,
    model: str = "gemini-2.5-pro",
) -> Agent:
    """Factory: returns a fresh optimist risk agent.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
        model: Gemini model ID. Default: gemini-2.5-pro (strong reasoning for risk analysis).
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
    )


def create_risk_pessimist(
    calibration_summary: str,
    model: str = "gemini-2.5-pro",
) -> Agent:
    """Factory: returns a fresh pessimist risk agent.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
        model: Gemini model ID. Default: gemini-2.5-pro (strong reasoning for risk analysis).
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
    )


def create_risk_debate(
    opt_calibration_summary: str,
    pess_calibration_summary: str,
    optimist_model: str = "gemini-2.5-pro",
    pessimist_model: str = "gemini-2.5-pro",
) -> SequentialAgent:
    """Factory: returns a SequentialAgent that runs optimist then pessimist.

    Both default to gemini-2.5-pro for strong reasoning on risk decisions.

    The optimist writes its verdict to state['optimist_verdict'].
    The pessimist reads that and writes to state['pessimist_verdict'].
    The coordinator reads both keys after the debate completes.

    Args:
        opt_calibration_summary: Calibration text for optimist prompt.
        pess_calibration_summary: Calibration text for pessimist prompt.
        optimist_model: Gemini model ID for the optimist agent.
        pessimist_model: Gemini model ID for the pessimist agent.
    """
    optimist = create_risk_optimist(opt_calibration_summary, model=optimist_model)
    pessimist = create_risk_pessimist(pess_calibration_summary, model=pessimist_model)

    return SequentialAgent(
        name="risk_debate",
        sub_agents=[optimist, pessimist],
        description="Two-agent adversarial risk debate: optimist then pessimist.",
    )
