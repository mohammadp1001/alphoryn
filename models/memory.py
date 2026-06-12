from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from models.enums import CycleOutcome, DebateWinner, MarketRegime, Strategy


class TradeRecord(BaseModel):
    """Written synchronously BEFORE submitting the order (write-ahead pattern)."""

    id: str  # UUID — also called trade_id externally
    session_id: str
    cycle_index: int = 0
    order_id: str  # Alpaca order ID
    symbol: str
    strategy: Strategy
    market_regime: MarketRegime
    side: str  # 'buy' | 'sell'
    qty: float
    entry_price: float = 0.0  # price at order submission
    optimist_verdict: str  # RiskLevel value
    pessimist_verdict: str  # RiskLevel value
    risk_level: str  # final RiskAssessment.level
    risk_score: float = 0.0
    opt_win_rate_at_trade: float = 0.5
    pess_win_rate_at_trade: float = 0.5
    filled_avg_price: float | None = None
    executed_at: datetime
    # filled after outcome resolution
    actual_pnl_pct: float | None = None
    debate_winner: DebateWinner | None = None
    outcome_resolved: bool = False
    outcome_timed_out: bool = False
    resolved_at: datetime | None = None


class AgentPairwise(BaseModel):
    """Pairwise win-rate record for one agent in one (regime, strategy) cell."""

    agent: str  # "optimist" | "pessimist"
    market_regime: MarketRegime
    strategy: Strategy
    wins: int = 0
    losses: int = 0
    ties: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.5

    @property
    def has_data(self) -> bool:
        return (self.wins + self.losses) >= 1


class RegimeStats(BaseModel):
    market_regime: MarketRegime
    total_trades: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    best_strategy: Strategy | None = None
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class CycleRecord(BaseModel):
    """Stored on PlanState.cycle_history after each cycle (committed or aborted)."""

    cycle_index: int
    outcome: CycleOutcome
    abort_reason: str | None = None  # populated for ABORTED
    abort_stage: str | None = None  # e.g. "HITL_REJECTED", "NO_SIGNALS", "EXECUTION_ERROR"
    shortlisted_symbols: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    trade_id: str | None = None  # populated for COMMITTED
    realised_pnl_pct: float | None = None
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class CalibrationContext(BaseModel):
    """Injected into risk agent system prompts before debate."""

    agent: str
    market_regime: MarketRegime
    strategy: Strategy
    win_rate: float
    wins: int
    losses: int
    has_data: bool
    formatted_summary: str  # pre-formatted string for system prompt injection


class UpdateResult(BaseModel):
    trade_id: str
    updated: bool
    debate_winner: DebateWinner | None = None
    actual_pnl_pct: float | None = None
