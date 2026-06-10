from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from models.enums import MarketRegime, OperatingMode, SessionOutcome, Strategy
from models.execution import Portfolio
from models.memory import CycleRecord
from models.risk import RiskAssessment


class SessionParams(BaseModel):
    """Set once via CLI wizard at session start."""
    timeframe_days: int = 3             # 1 | 3 | 5 — lookback window for analysis
    strategy: Strategy = Strategy.MOMENTUM
    mode: OperatingMode = OperatingMode.SEMI_AUTO
    loss_limit_eur: float = 500.0
    shortlist_n: int = 2                # 1–5, default 2
    hitl_timeout_seconds: int = 60
    hitl_timeout_action: str = "abort"  # "abort" | "proceed"
    universe: str = "US_SECTOR_ETFS"   # key into config.ETF_UNIVERSES


class PlanState(BaseModel):
    """
    Coordinator's single source of truth for the session.
    Never shared with subagents directly — subagents receive only their task inputs.
    """
    session_id: str                     # UUID generated at session start
    params: SessionParams
    started_at: datetime = Field(default_factory=datetime.utcnow)

    # Set once by research agent at session start
    market_regime: MarketRegime | None = None

    # Updated on each cycle
    cycle_index: int = 0
    cycle_history: list[CycleRecord] = Field(default_factory=list)

    # Portfolio snapshot loaded at session start, refreshed each cycle
    portfolio_snapshot: Portfolio | None = None

    # Realised P&L accumulated this session (from COMMITTED cycles only)
    session_realised_pnl_eur: float = 0.0

    # Last risk assessment from most recent debate
    last_risk_assessment: RiskAssessment | None = None

    # Set when session ends
    closed_at: datetime | None = None
    outcome: SessionOutcome | None = None

    @property
    def loss_limit_consumed_pct(self) -> float:
        if self.params.loss_limit_eur <= 0:
            return 0.0
        loss = max(0.0, -self.session_realised_pnl_eur)
        return loss / self.params.loss_limit_eur

    @property
    def loss_limit_breached(self) -> bool:
        return self.loss_limit_consumed_pct >= 1.0

    @property
    def loss_limit_warning(self) -> bool:
        return self.loss_limit_consumed_pct >= 0.8

    def complete_cycle(self, record: CycleRecord) -> None:
        self.cycle_history.append(record)
        self.cycle_index += 1
        if record.realised_pnl_pct is not None and record.outcome.value == "COMMITTED":
            portfolio_value = (
                self.portfolio_snapshot.portfolio_value
                if self.portfolio_snapshot
                else 0.0
            )
            self.session_realised_pnl_eur += (record.realised_pnl_pct / 100) * portfolio_value
