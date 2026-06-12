from __future__ import annotations

from pydantic import BaseModel

from models.analysis import BacktestResult, RankedSignals
from models.enums import MarketRegime, RiskLevel, Strategy
from models.research import SentimentReport


class CandidateShortlist(BaseModel):
    """Top-N ETFs selected by coordinator from RankedSignals for the risk debate."""

    symbols: list[str]
    ranked_signals: RankedSignals
    selection_reasoning: str


class AgentCalibration(BaseModel):
    """Win-rate calibration for one agent in one (regime, strategy) context."""

    agent: str  # "optimist" | "pessimist"
    market_regime: MarketRegime
    strategy: Strategy
    wins: int
    losses: int
    ties: int
    win_rate: float  # wins / (wins + losses), 0.5 if no data
    has_data: bool  # False on cold start


class DebateInput(BaseModel):
    """Everything passed into the risk debate."""

    shortlist: CandidateShortlist
    backtest_results: list[BacktestResult]
    sentiment_report: SentimentReport
    optimist_calibration: AgentCalibration
    pessimist_calibration: AgentCalibration


class AgentVerdict(BaseModel):
    """One risk agent's output after its 2-turn debate."""

    agent: str  # "optimist" | "pessimist"
    recommended_level: RiskLevel
    reasoning: str
    acknowledged_opposing_signal: str  # constitution requirement


class RiskAssessment(BaseModel):
    """
    Coordinator's final synthesis after the debate.
    Level is computed deterministically — see ADR 0001.
    """

    level: RiskLevel
    optimist_verdict: AgentVerdict
    pessimist_verdict: AgentVerdict
    synthesis_reasoning: str  # written by LLM, level computed by formula
    weighted_score: float  # the raw score from the formula
    override_applied: bool = False  # True if asymmetric pessimist override triggered

    @classmethod
    def synthesise(
        cls,
        optimist_verdict: AgentVerdict,
        pessimist_verdict: AgentVerdict,
        opt_win_rate: float,
        pess_win_rate: float,
        synthesis_reasoning: str,
    ) -> RiskAssessment:
        from config import (
            PESSIMIST_OVERRIDE_WIN_RATE,
            RISK_HIGH_THRESHOLD,
            RISK_LOW_THRESHOLD,
        )

        level_map = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
        opt_val = level_map[optimist_verdict.recommended_level]
        pess_val = level_map[pessimist_verdict.recommended_level]

        total_weight = opt_win_rate + pess_win_rate
        if total_weight == 0:
            total_weight = 1.0
            opt_win_rate = 0.5
            pess_win_rate = 0.5

        score = (opt_val * opt_win_rate + pess_val * pess_win_rate) / total_weight

        override = (
            pess_win_rate > PESSIMIST_OVERRIDE_WIN_RATE
            and pessimist_verdict.recommended_level == RiskLevel.HIGH
        )

        if override:
            level = RiskLevel.HIGH
        elif score < RISK_LOW_THRESHOLD:
            level = RiskLevel.LOW
        elif score > RISK_HIGH_THRESHOLD:
            level = RiskLevel.HIGH
        else:
            level = RiskLevel.MEDIUM

        return cls(
            level=level,
            optimist_verdict=optimist_verdict,
            pessimist_verdict=pessimist_verdict,
            synthesis_reasoning=synthesis_reasoning,
            weighted_score=score,
            override_applied=override,
        )
