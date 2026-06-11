"""Unit tests for models.session — SessionParams, PlanState."""
from __future__ import annotations

from datetime import datetime, timedelta

from models.enums import (
    CycleOutcome,
    OperatingMode,
    SessionTimeframe,
)
from models.memory import CycleRecord
from models.session import PlanState, SessionParams

# ── SessionParams ─────────────────────────────────────────────────────────────

def test_session_params_defaults():
    params = SessionParams()
    assert params.mode == OperatingMode.SEMI_AUTO
    assert params.loss_limit_eur == 500.0
    assert params.timeframe == SessionTimeframe.DAY_1
    assert params.shortlist_n == 2
    assert params.hitl_timeout_seconds == 60
    assert params.hitl_timeout_action == "abort"


def test_session_params_custom_values():
    params = SessionParams(
        mode=OperatingMode.FULL_AUTO,
        loss_limit_eur=1000.0,
        timeframe=SessionTimeframe.DAY_5,
        shortlist_n=4,
        hitl_timeout_seconds=120,
        hitl_timeout_action="confirm",
    )
    assert params.mode == OperatingMode.FULL_AUTO
    assert params.loss_limit_eur == 1000.0
    assert params.timeframe == SessionTimeframe.DAY_5


def test_session_params_duration_property():
    assert SessionParams(timeframe=SessionTimeframe.MIN_30).duration == timedelta(minutes=30)
    assert SessionParams(timeframe=SessionTimeframe.HOUR_1).duration == timedelta(hours=1)
    assert SessionParams(timeframe=SessionTimeframe.HOUR_3).duration == timedelta(hours=3)
    assert SessionParams(timeframe=SessionTimeframe.HOUR_12).duration == timedelta(hours=12)
    assert SessionParams(timeframe=SessionTimeframe.DAY_1).duration == timedelta(days=1)
    assert SessionParams(timeframe=SessionTimeframe.DAY_2).duration == timedelta(days=2)
    assert SessionParams(timeframe=SessionTimeframe.DAY_5).duration == timedelta(days=5)


# ── PlanState ─────────────────────────────────────────────────────────────────

def _make_plan_state(session_id="test-id", **kwargs) -> PlanState:
    params = SessionParams(**kwargs)
    return PlanState(session_id=session_id, params=params)


def test_plan_state_defaults():
    ps = _make_plan_state()
    assert ps.session_id == "test-id"
    assert ps.cycle_index == 0
    assert ps.session_realised_pnl_eur == 0.0
    assert ps.market_regime is None
    assert ps.cycle_history == []
    assert ps.portfolio_snapshot is None
    assert ps.closed_at is None
    assert ps.outcome is None


def test_plan_state_started_at_is_set():
    before = datetime.utcnow()
    ps = _make_plan_state()
    after = datetime.utcnow()
    assert before <= ps.started_at <= after


# ── loss_limit_consumed_pct ───────────────────────────────────────────────────

def test_loss_limit_consumed_pct_zero_loss():
    ps = _make_plan_state()
    assert ps.loss_limit_consumed_pct == 0.0


def test_loss_limit_consumed_pct_partial():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = -250.0  # 50% of 500
    assert abs(ps.loss_limit_consumed_pct - 0.5) < 0.001


def test_loss_limit_consumed_pct_full():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = -500.0
    assert ps.loss_limit_consumed_pct >= 1.0


def test_loss_limit_consumed_pct_profit_is_zero():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = 200.0  # profit
    # max(0, -200) = 0
    assert ps.loss_limit_consumed_pct == 0.0


def test_loss_limit_consumed_pct_zero_limit():
    ps = _make_plan_state(loss_limit_eur=0.0)
    assert ps.loss_limit_consumed_pct == 0.0


# ── loss_limit_breached ───────────────────────────────────────────────────────

def test_loss_limit_breached_false_when_ok():
    ps = _make_plan_state()
    assert ps.loss_limit_breached is False


def test_loss_limit_breached_true_at_limit():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = -500.0
    assert ps.loss_limit_breached is True


def test_loss_limit_breached_true_beyond_limit():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = -600.0
    assert ps.loss_limit_breached is True


# ── loss_limit_warning ────────────────────────────────────────────────────────

def test_loss_limit_warning_false_below_80():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = -300.0  # 60%
    assert ps.loss_limit_warning is False


def test_loss_limit_warning_true_at_80():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = -400.0  # 80%
    assert ps.loss_limit_warning is True


def test_loss_limit_warning_true_above_80():
    ps = _make_plan_state()
    ps.session_realised_pnl_eur = -450.0  # 90%
    assert ps.loss_limit_warning is True


# ── complete_cycle ────────────────────────────────────────────────────────────

def _make_cycle_record(outcome: CycleOutcome, pnl: float | None = None) -> CycleRecord:
    return CycleRecord(
        cycle_index=0,
        outcome=outcome,
        shortlisted_symbols=["XLK"],
        risk_level="MEDIUM",
        trade_id="t-1",
        realised_pnl_pct=pnl,
    )


def test_complete_cycle_increments_cycle_index():
    ps = _make_plan_state()
    cycle = _make_cycle_record(CycleOutcome.COMMITTED, pnl=1.5)
    ps.complete_cycle(cycle)
    assert ps.cycle_index == 1


def test_complete_cycle_appends_to_history():
    ps = _make_plan_state()
    cycle = _make_cycle_record(CycleOutcome.COMMITTED, pnl=1.0)
    ps.complete_cycle(cycle)
    assert len(ps.cycle_history) == 1
    assert ps.cycle_history[0] is cycle


def test_complete_cycle_committed_updates_pnl_with_portfolio():
    from models.execution import Portfolio

    ps = _make_plan_state()
    ps.portfolio_snapshot = Portfolio(
        account_id="paper-acct",
        equity=10000.0,
        cash=5000.0,
        buying_power=5000.0,
        portfolio_value=10000.0,
        positions=[],
    )

    cycle = _make_cycle_record(CycleOutcome.COMMITTED, pnl=2.0)  # 2% of 10000 = 200 EUR
    ps.complete_cycle(cycle)
    assert abs(ps.session_realised_pnl_eur - 200.0) < 0.01


def test_complete_cycle_committed_no_portfolio_snapshot():
    ps = _make_plan_state()
    ps.portfolio_snapshot = None

    cycle = _make_cycle_record(CycleOutcome.COMMITTED, pnl=2.0)
    ps.complete_cycle(cycle)
    # portfolio_value = 0 → pnl_eur = 0
    assert ps.session_realised_pnl_eur == 0.0


def test_complete_cycle_aborted_does_not_update_pnl():
    ps = _make_plan_state()
    cycle = _make_cycle_record(CycleOutcome.ABORTED, pnl=None)
    ps.complete_cycle(cycle)
    assert ps.session_realised_pnl_eur == 0.0


def test_complete_cycle_none_pnl_committed_no_update():
    ps = _make_plan_state()
    cycle = _make_cycle_record(CycleOutcome.COMMITTED, pnl=None)
    ps.complete_cycle(cycle)
    assert ps.session_realised_pnl_eur == 0.0


def test_complete_multiple_cycles():
    from models.execution import Portfolio

    ps = _make_plan_state()
    ps.portfolio_snapshot = Portfolio(
        account_id="paper-acct",
        equity=10000.0,
        cash=5000.0,
        buying_power=5000.0,
        portfolio_value=10000.0,
        positions=[],
    )

    c1 = CycleRecord(cycle_index=0, outcome=CycleOutcome.COMMITTED,
                     shortlisted_symbols=[], risk_level="LOW", realised_pnl_pct=1.0)
    c2 = CycleRecord(cycle_index=1, outcome=CycleOutcome.COMMITTED,
                     shortlisted_symbols=[], risk_level="MEDIUM", realised_pnl_pct=-0.5)
    c3 = CycleRecord(cycle_index=2, outcome=CycleOutcome.ABORTED,
                     shortlisted_symbols=[], risk_level="HIGH", realised_pnl_pct=None)

    ps.complete_cycle(c1)
    ps.complete_cycle(c2)
    ps.complete_cycle(c3)

    assert ps.cycle_index == 3
    assert len(ps.cycle_history) == 3
    # net pnl: (1.0 - 0.5)% of 10000 = 50
    assert abs(ps.session_realised_pnl_eur - 50.0) < 0.1
