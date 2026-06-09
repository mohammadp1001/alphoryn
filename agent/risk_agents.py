"""Risk debate agent factories — optimist and pessimist for SequentialAgent."""
from __future__ import annotations

from google.adk.agents import Agent, SequentialAgent  # type: ignore[import]

from agent.prompts import RISK_OPTIMIST_INSTRUCTION, RISK_PESSIMIST_INSTRUCTION


def create_risk_optimist(calibration_summary: str) -> Agent:
    """Factory: returns a fresh optimist risk agent.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
    """
    return Agent(
        name="risk_optimist",
        model="gemini-2.5-flash",
        instruction=RISK_OPTIMIST_INSTRUCTION.format(
            calibration_summary=calibration_summary
        ),
        tools=[],
        description="Argues for the lowest justifiable risk level for a trade candidate.",
        output_key="optimist_verdict",
    )


def create_risk_pessimist(calibration_summary: str) -> Agent:
    """Factory: returns a fresh pessimist risk agent.

    Args:
        calibration_summary: Pre-formatted calibration string injected into system prompt.
    """
    return Agent(
        name="risk_pessimist",
        model="gemini-2.5-flash",
        instruction=RISK_PESSIMIST_INSTRUCTION.format(
            calibration_summary=calibration_summary
        ),
        tools=[],
        description=(
            "Argues for the highest justifiable risk level for a trade candidate. "
            "Reads the optimist verdict from state key 'optimist_verdict'."
        ),
        output_key="pessimist_verdict",
    )


def create_risk_debate(opt_calibration_summary: str, pess_calibration_summary: str) -> SequentialAgent:
    """Factory: returns a SequentialAgent that runs optimist then pessimist.

    The optimist writes its verdict to state['optimist_verdict'].
    The pessimist reads that and writes to state['pessimist_verdict'].
    The coordinator reads both keys after the debate completes.

    Args:
        opt_calibration_summary: Calibration text for optimist prompt.
        pess_calibration_summary: Calibration text for pessimist prompt.
    """
    optimist = create_risk_optimist(opt_calibration_summary)
    pessimist = create_risk_pessimist(pess_calibration_summary)

    return SequentialAgent(
        name="risk_debate",
        sub_agents=[optimist, pessimist],
        description="Two-agent adversarial risk debate: optimist then pessimist.",
    )
