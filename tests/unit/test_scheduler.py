"""Unit tests for alphoryn/scheduler/scheduler.py (T016 + T029/T030 scope)."""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

from alphoryn.agents.main_agent import MainAgentError
from alphoryn.config.models import AlphorynConfig
from alphoryn.execution.agent import AssetDecision, SessionDecision
from alphoryn.monitor.monitor import PositionMonitor
from alphoryn.scheduler.scheduler import Scheduler, SessionSkip
from alphoryn.usage import TokenUsage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cfg(**kwargs) -> AlphorynConfig:
    defaults = {
        "tickers": ["SPY", "QQQ"],
        "candle_timeframe": "1H",
        "run_duration": "24H",
    }
    defaults.update(kwargs)
    return AlphorynConfig(**defaults)


def _scheduler(**cfg_kwargs) -> Scheduler:
    bank = MagicMock()
    return Scheduler(_cfg(**cfg_kwargs), bank)


# ---------------------------------------------------------------------------
# Default budget derivation — proportional to candle timeframe (87% / 13%)
# ---------------------------------------------------------------------------


def test_default_budget_10min() -> None:
    sched = _scheduler(candle_timeframe="10min")
    assert sched._investigation_budget == int(600 * 0.87)
    assert sched._execute_budget == int(600 * 0.13)


def test_default_budget_30min() -> None:
    sched = _scheduler(candle_timeframe="30min")
    assert sched._investigation_budget == int(1800 * 0.87)
    assert sched._execute_budget == int(1800 * 0.13)


def test_default_budget_1h() -> None:
    sched = _scheduler(candle_timeframe="1H")
    assert sched._investigation_budget == int(3600 * 0.87)  # 3132 s = 52 min
    assert sched._execute_budget == int(3600 * 0.13)        # 468 s = 7 min 48 s


def test_default_budget_4h() -> None:
    sched = _scheduler(candle_timeframe="4H")
    assert sched._investigation_budget == int(14400 * 0.87)  # 12528 s = 208 min 48 s
    assert sched._execute_budget == int(14400 * 0.13)        # 1872 s = 31 min 12 s


def test_injected_budget_overrides_default() -> None:
    bank = MagicMock()
    sched = Scheduler(
        _cfg(candle_timeframe="1H"),
        bank,
        _investigation_budget_secs=99,
        _execute_budget_secs=11,
    )
    assert sched._investigation_budget == 99
    assert sched._execute_budget == 11


# ---------------------------------------------------------------------------
# compute_next_candle_close — 1H
# ---------------------------------------------------------------------------


def test_next_candle_close_1h_not_on_boundary() -> None:
    sched = _scheduler(candle_timeframe="1H")
    # 14:22:00 UTC → next boundary is 15:00:00
    now = datetime(2024, 1, 15, 14, 22, 0, tzinfo=UTC)
    result = sched.compute_next_candle_close(now)
    assert result == datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)


def test_next_candle_close_1h_exactly_on_boundary() -> None:
    sched = _scheduler(candle_timeframe="1H")
    # Exactly on the boundary → next is +1H
    now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
    result = sched.compute_next_candle_close(now)
    assert result == datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)


def test_next_candle_close_1h_one_second_before_boundary() -> None:
    sched = _scheduler(candle_timeframe="1H")
    now = datetime(2024, 1, 15, 14, 59, 59, tzinfo=UTC)
    result = sched.compute_next_candle_close(now)
    assert result == datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# compute_next_candle_close — 30min
# ---------------------------------------------------------------------------


def test_next_candle_close_30min_at_15_minutes() -> None:
    sched = _scheduler(candle_timeframe="30min")
    now = datetime(2024, 1, 15, 14, 15, 0, tzinfo=UTC)
    result = sched.compute_next_candle_close(now)
    assert result == datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)


def test_next_candle_close_30min_at_45_minutes() -> None:
    sched = _scheduler(candle_timeframe="30min")
    now = datetime(2024, 1, 15, 14, 45, 0, tzinfo=UTC)
    result = sched.compute_next_candle_close(now)
    assert result == datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# compute_next_candle_close — 4H
# ---------------------------------------------------------------------------


def test_next_candle_close_4h_at_10_utc() -> None:
    sched = _scheduler(candle_timeframe="4H")
    now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    result = sched.compute_next_candle_close(now)
    assert result == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)


def test_next_candle_close_4h_at_23_utc() -> None:
    sched = _scheduler(candle_timeframe="4H")
    now = datetime(2024, 1, 15, 23, 0, 0, tzinfo=UTC)
    result = sched.compute_next_candle_close(now)
    assert result == datetime(2024, 1, 16, 0, 0, 0, tzinfo=UTC)


def test_next_candle_close_result_always_after_now() -> None:
    for tf in ("30min", "1H", "4H"):
        sched = _scheduler(candle_timeframe=tf)
        now = datetime(2024, 1, 15, 14, 33, 27, tzinfo=UTC)
        result = sched.compute_next_candle_close(now)
        assert result > now


# ---------------------------------------------------------------------------
# get_market_clock
# ---------------------------------------------------------------------------


def test_get_market_clock_calls_alpaca_trading_client() -> None:
    sched = _scheduler()
    mock_clock = MagicMock()
    mock_client = MagicMock()
    mock_client.get_clock.return_value = mock_clock

    with patch("alphoryn.scheduler.scheduler.TradingClient", return_value=mock_client):
        result = sched.get_market_clock()

    assert result is mock_clock


# ---------------------------------------------------------------------------
# is_market_open
# ---------------------------------------------------------------------------


def test_is_market_open_true_when_open() -> None:
    sched = _scheduler()
    mock_clock = MagicMock()
    mock_clock.is_open = True
    with patch.object(sched, "get_market_clock", return_value=mock_clock):
        assert sched.is_market_open() is True


def test_is_market_open_false_when_closed() -> None:
    sched = _scheduler()
    mock_clock = MagicMock()
    mock_clock.is_open = False
    with patch.object(sched, "get_market_clock", return_value=mock_clock):
        assert sched.is_market_open() is False


def test_is_market_open_holds_safe_on_api_error() -> None:
    """Issue #137: an unreachable clock must hold, not trade blind."""
    sched = _scheduler()
    buf = StringIO()
    with (
        patch.object(sched, "get_market_clock", side_effect=RuntimeError("no conn")),
        patch("sys.stderr", buf),
    ):
        assert sched.is_market_open() is False
    assert "WARN" in buf.getvalue()
    assert "no conn" in buf.getvalue()


def test_is_market_open_holds_safe_when_clock_has_no_is_open() -> None:
    """Issue #137: a malformed clock object must not read as open."""
    sched = _scheduler()
    clock = object()  # no is_open attribute
    buf = StringIO()
    with patch.object(sched, "get_market_clock", return_value=clock), patch("sys.stderr", buf):
        assert sched.is_market_open() is False
    assert "WARN" in buf.getvalue()


def test_is_market_open_true_when_extended_hours_set() -> None:
    sched = _scheduler(extended_hours=True)
    # get_market_clock must never be called when extended_hours=True
    with patch.object(sched, "get_market_clock", side_effect=AssertionError("must not call")) as m:
        assert sched.is_market_open() is True
    m.assert_not_called()


# ---------------------------------------------------------------------------
# wait_for_candle_close
# ---------------------------------------------------------------------------


def test_wait_for_candle_close_prints_countdown_line() -> None:
    sched = _scheduler()
    future = datetime.now(UTC).replace(microsecond=0)
    # target already passed → immediate exit
    with patch("alphoryn.scheduler.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = future + timedelta(seconds=1)
        mock_dt.fromtimestamp = datetime.fromtimestamp
        buf = StringIO()
        sleep_calls: list = []
        with patch("sys.stdout", buf):
            sched.wait_for_candle_close(future, _sleep=sleep_calls.append)
    # A countdown line must have been printed (even if wait = 0)
    assert "Waiting for next candle close at" in buf.getvalue()


def test_wait_for_candle_close_sleeps_in_1s_increments() -> None:
    sched = _scheduler()
    future = datetime(2024, 1, 15, 16, 0, 0, tzinfo=UTC)

    times = [
        datetime(2024, 1, 15, 15, 59, 35, tzinfo=UTC),  # total_secs baseline
        datetime(2024, 1, 15, 15, 59, 35, tzinfo=UTC),  # 25s remaining
        datetime(2024, 1, 15, 15, 59, 45, tzinfo=UTC),  # 15s remaining
        datetime(2024, 1, 15, 15, 59, 55, tzinfo=UTC),  # 5s remaining
        datetime(2024, 1, 15, 16, 0, 1, tzinfo=UTC),    # past target → exit
    ]
    idx = [0]

    def fake_now(tz=None):
        t = times[min(idx[0], len(times) - 1)]
        idx[0] += 1
        return t

    sleep_args: list[float] = []

    with patch("alphoryn.scheduler.scheduler.datetime") as mock_dt:
        mock_dt.now.side_effect = fake_now
        mock_dt.fromtimestamp = datetime.fromtimestamp
        sched.wait_for_candle_close(future, _sleep=sleep_args.append)

    # All sleep durations must be ≤ 1
    assert all(s <= 1.0 for s in sleep_args)
    assert len(sleep_args) >= 1


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_waits_until_next_candle_close() -> None:
    sched = _scheduler(candle_timeframe="1H")
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close") as mock_wait,
    ):
        sched.run()
    mock_wait.assert_called_once()
    call_kwargs = mock_wait.call_args
    assert call_kwargs[0][0] == mock_target


# ---------------------------------------------------------------------------
# run — full session loop (T029 / T030)
# ---------------------------------------------------------------------------

_FIXTURE_DECISION = SessionDecision(
    session_id="run-1/session-0001",
    decisions=[
        AssetDecision(
            ticker="SPY",
            action="BUY",
            strategy="MEAN_REVERSION",
            lot_size=5,
            exit_target={"type": "price_level", "value": 460.0},
            reasoning="ADX low.",
        ),
        AssetDecision(
            ticker="QQQ",
            action="HOLD",
            strategy="MOMENTUM",
            lot_size=None,
            exit_target=None,
            reasoning="No regime.",
        ),
    ],
)


def _full_scheduler(**extra) -> Scheduler:
    """Build a scheduler with 1 session and mock agents/logger."""
    bank = MagicMock()
    bank.start_run.return_value = 1
    bank.get_feedback_blocked_tickers.return_value = set()
    # A bare MagicMock is truthy, which makes the `while load_open_positions()`
    # drain loop in run()'s finally block spin forever (issue #165). Tests that
    # exercise draining set their own return_value/side_effect.
    bank.load_open_positions.return_value = []
    cfg = AlphorynConfig(
        tickers=["SPY", "QQQ"],
        candle_timeframe="1H",
        run_duration="1H",  # session_count = 1
    )
    main_agent = MagicMock()
    main_agent.decide.return_value = _FIXTURE_DECISION
    # Real values, not MagicMocks: the end-of-run cost summary adds usage and
    # prices it by model, and a MagicMock in either slot is not a token count.
    main_agent.usage = TokenUsage()
    main_agent.model = "gemini-2.5-pro"
    execution_agent = MagicMock()
    # Explicit, not a bare MagicMock: execute() returns the per-ticker
    # execution_result the session record carries (issue #131).
    execution_agent.execute.return_value = {"SPY": "EXECUTED", "QQQ": "EXECUTED"}
    logger = MagicMock()
    return Scheduler(
        cfg,
        bank,
        main_agent=main_agent,
        execution_agent=execution_agent,
        logger=logger,
        **extra,
    )


def _run_with_no_wait(sched: Scheduler) -> None:
    """Run the scheduler with all waits and market checks stubbed out."""
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close"),
        patch.object(sched, "is_market_open", return_value=True),
    ):
        sched.run()


def test_run_startup_only_when_no_agents() -> None:
    sched = _scheduler(candle_timeframe="1H")
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close") as mock_wait,
    ):
        sched.run()
    mock_wait.assert_called_once()  # startup alignment only


def test_run_starts_run_in_bank() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    sched._bank.start_run.assert_called_once()


def test_run_ends_run_in_bank() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    sched._bank.end_run.assert_called_once_with(1)


def test_run_emits_session_start_telemetry() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    emitted = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "SESSION_START" in emitted


def test_run_emits_session_end_telemetry() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    emitted = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "SESSION_END" in emitted


def test_run_writes_session_to_bank() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    sched._bank.write_session.assert_called_once()


def test_run_writes_memory_entries_for_both_tickers() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    assert sched._bank.write_memory_entry.call_count == 2


def test_run_calls_main_agent_decide() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    sched._main_agent.decide.assert_called_once()


def test_run_calls_execution_agent_execute() -> None:
    sched = _full_scheduler()
    _run_with_no_wait(sched)
    sched._execution_agent.execute.assert_called_once_with(_FIXTURE_DECISION)


# ---------------------------------------------------------------------------
# Market closed — MARKET_CLOSED telemetry, session not counted
# ---------------------------------------------------------------------------


def test_run_emits_market_closed_when_market_closed() -> None:
    sched = _full_scheduler()
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

    call_count = [0]

    def market_open_side_effect() -> bool:
        call_count[0] += 1
        if call_count[0] == 1:
            return False  # first check: closed
        return True  # second check: open

    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close"),
        patch.object(sched, "is_market_open", side_effect=market_open_side_effect),
    ):
        sched.run()

    emitted = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "MARKET_CLOSED" in emitted


def test_run_does_not_count_closed_market_session() -> None:
    sched = _full_scheduler()
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

    call_count = [0]

    def market_open_side_effect() -> bool:
        call_count[0] += 1
        if call_count[0] == 1:
            return False  # first: closed (not counted)
        return True  # second: open (counted)

    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close"),
        patch.object(sched, "is_market_open", side_effect=market_open_side_effect),
    ):
        sched.run()

    # Still processes exactly 1 *countable* session (session_count=1). The
    # closed-market candle is persisted too (issue #136) but is not counted.
    statuses = [c.args[0].status for c in sched._bank.write_session.call_args_list]
    assert statuses == ["SKIPPED_MARKET_CLOSED", "COMPLETED"]


def test_run_persists_a_session_row_for_a_closed_market_candle() -> None:
    """Issue #136 / SC-003: no session ends silently."""
    sched = _full_scheduler()
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
    call_count = [0]

    def market_open_side_effect() -> bool:
        call_count[0] += 1
        return call_count[0] != 1

    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close"),
        patch.object(sched, "is_market_open", side_effect=market_open_side_effect),
    ):
        sched.run()

    skipped = sched._bank.write_session.call_args_list[0].args[0]
    assert skipped.status == "SKIPPED_MARKET_CLOSED"
    assert skipped.id == "run-1/session-0001"
    assert skipped.run_id == 1
    assert skipped.html_report_path is None
    assert skipped.ticker_decisions is None
    # The countable session that follows takes the next ordinal, so IDs stay unique.
    assert sched._bank.write_session.call_args_list[1].args[0].id == "run-1/session-0002"


def test_process_session_writes_data_unavailable_status() -> None:
    """Issue #136: SKIPPED_DATA_UNAVAILABLE is reachable, not just declared."""
    sched = _full_scheduler()
    with patch.object(
        sched, "_run_investigation", return_value=(None, SessionSkip("SKIPPED_DATA_UNAVAILABLE"))
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    assert sched._bank.write_session.call_args.args[0].status == "SKIPPED_DATA_UNAVAILABLE"


def test_process_session_writes_agent_error_status() -> None:
    """An agent failure is its own status, not a market-data one."""
    sched = _full_scheduler()
    with patch.object(
        sched, "_run_investigation", return_value=(None, SessionSkip("SKIPPED_AGENT_ERROR", "boom"))
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    assert sched._bank.write_session.call_args.args[0].status == "SKIPPED_AGENT_ERROR"


# ---------------------------------------------------------------------------
# Budget timeout (T029)
# ---------------------------------------------------------------------------


# These drive _process_session directly rather than run(). A timed-out session
# is not counted against session_count (FR-018), so a scheduler whose every
# session times out never satisfies `sessions_completed < session_count` and
# run() spins forever once the waits are stubbed out (issue #165).


def test_investigation_timeout_emits_budget_timeout() -> None:
    sched = _full_scheduler(_investigation_budget_secs=0)
    # Make decide() block long enough for timeout
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION

    sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    emitted = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "BUDGET_TIMEOUT" in emitted


def test_investigation_timeout_writes_skipped_session() -> None:
    sched = _full_scheduler(_investigation_budget_secs=0)
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION

    status = sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    assert status == "SKIPPED_TIMEOUT"
    sched._bank.write_session.assert_called_once()
    session_arg = sched._bank.write_session.call_args.args[0]
    assert session_arg.status == "SKIPPED_TIMEOUT"


def test_run_loop_does_not_count_a_timed_out_session() -> None:
    """FR-018: a timed-out session must not consume the run's session budget.

    Guards the loop condition itself without letting it spin: the first pass
    times out, the second succeeds and ends the run.
    """
    sched = _full_scheduler()
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
    statuses = iter(["SKIPPED_TIMEOUT", "COMPLETED"])

    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close"),
        patch.object(sched, "is_market_open", return_value=True),
        patch.object(sched, "_process_session", side_effect=lambda *a: next(statuses)) as proc,
    ):
        sched.run()

        # Two passes were needed to bank one countable session.
        assert proc.call_count == 2


def test_execute_timeout_emits_budget_timeout() -> None:
    sched = _full_scheduler(_execute_budget_secs=0)
    sched._execution_agent.execute.side_effect = lambda *a: time.sleep(0.5)

    _run_with_no_wait(sched)

    emitted = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "BUDGET_TIMEOUT" in emitted


# ---------------------------------------------------------------------------
# Heartbeat (T029)
# ---------------------------------------------------------------------------


class _ControlledEvent(threading.Event):
    """Fires the loop body exactly N times before stopping."""

    def __init__(self, fire_count: int = 1) -> None:
        super().__init__()
        self._remaining = fire_count

    def wait(self, timeout: float | None = None) -> bool:  # type: ignore[override]
        if self._remaining > 0:
            self._remaining -= 1
            return False  # not set → heartbeat body executes
        self.set()
        return True  # set → loop exits


def test_heartbeat_loop_prints_investigating_line(capsys) -> None:
    sched = _full_scheduler(_heartbeat_interval_secs=1)
    stop = _ControlledEvent(fire_count=1)
    sched._heartbeat_loop("run-1/session-0001", stop)
    captured = capsys.readouterr()
    assert "investigating" in captured.out


def test_heartbeat_loop_exits_when_stop_event_set() -> None:
    sched = _full_scheduler(_heartbeat_interval_secs=1)
    stop = _ControlledEvent(fire_count=0)  # stops immediately
    sched._heartbeat_loop("run-1/session-0001", stop)
    # If it didn't exit, the test would hang


# ---------------------------------------------------------------------------
# _run_investigation — direct tests
# ---------------------------------------------------------------------------


def test_run_investigation_returns_decision_on_success() -> None:
    sched = _full_scheduler()
    result = sched._run_investigation("sess-001", datetime.now(UTC), ["SPY", "QQQ"])
    assert result == (_FIXTURE_DECISION, None)


def test_run_investigation_returns_timeout_status_on_timeout() -> None:
    sched = _full_scheduler(_investigation_budget_secs=0)
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION
    result = sched._run_investigation("sess-001", datetime.now(UTC), ["SPY", "QQQ"])
    assert result == (None, SessionSkip("SKIPPED_TIMEOUT"))


def test_run_investigation_returns_data_unavailable_when_market_data_raises() -> None:
    """Issue #136: a market-data failure skips the session, it does not crash the run."""
    sched = _full_scheduler()
    sched._main_agent.decide.side_effect = RuntimeError("alpaca down")
    buf = StringIO()
    with patch("sys.stderr", buf):
        result = sched._run_investigation("sess-001", datetime.now(UTC), ["SPY", "QQQ"])
    assert result == (None, SessionSkip("SKIPPED_DATA_UNAVAILABLE", "alpaca down"))
    assert "alpaca down" in buf.getvalue()


def test_run_investigation_separates_an_agent_failure_from_a_data_failure() -> None:
    """2026-08-13: two sessions died on the model and were filed as data outages.

    A MainAgentError means the agent was reached and gave an unusable answer -
    an unparseable reply, or none at all because the provider returned 429.
    Market data was never involved.
    """
    sched = _full_scheduler()
    sched._main_agent.decide.side_effect = MainAgentError(
        "main_agent response is not valid JSON: Expecting value: line 1 column 1 (char 0)"
    )
    buf = StringIO()
    with patch("sys.stderr", buf):
        decision, skip = sched._run_investigation("sess-001", datetime.now(UTC), ["SPY"])

    assert decision is None
    assert skip.status == "SKIPPED_AGENT_ERROR"
    assert "not valid JSON" in skip.detail
    assert "Investigation failed (agent)" in buf.getvalue()


# ---------------------------------------------------------------------------
# _run_execute — direct tests
# ---------------------------------------------------------------------------


def test_run_execute_calls_execution_agent() -> None:
    sched = _full_scheduler()
    sched._run_execute(_FIXTURE_DECISION)
    sched._execution_agent.execute.assert_called_once_with(_FIXTURE_DECISION)


# ---------------------------------------------------------------------------
# _process_session — decision is None (timeout path)
# ---------------------------------------------------------------------------


def test_process_session_with_none_decision_writes_skipped_session() -> None:
    sched = _full_scheduler()
    sched._main_agent = None  # force decision = None via direct override

    # Manually patch _run_investigation to return None
    with patch.object(
        sched, "_run_investigation", return_value=(None, SessionSkip("SKIPPED_TIMEOUT"))
    ):
        sched._process_session(
            run_id=1,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=datetime.now(UTC),
        )

    session_arg = sched._bank.write_session.call_args.args[0]
    assert session_arg.status == "SKIPPED_TIMEOUT"
    sched._bank.write_memory_entry.assert_not_called()


def test_process_session_no_report_when_report_generator_is_none() -> None:
    sched = _full_scheduler()
    sched._report_generator = None

    with patch.object(sched, "_run_investigation", return_value=(_FIXTURE_DECISION, None)):
        sched._process_session(
            run_id=1,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=datetime.now(UTC),
        )

    session_arg = sched._bank.write_session.call_args.args[0]
    assert session_arg.html_report_path is None


def test_process_session_with_report_generator_writes_path() -> None:
    sched = _full_scheduler()
    mock_gen = MagicMock()
    mock_gen.write.return_value = "/reports/run-1/session-0001.html"
    sched._report_generator = mock_gen

    with patch.object(sched, "_run_investigation", return_value=(_FIXTURE_DECISION, None)):
        sched._process_session(
            run_id=1,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=datetime.now(UTC),
        )

    session_arg = sched._bank.write_session.call_args.args[0]
    assert session_arg.html_report_path == "/reports/run-1/session-0001.html"


def test_process_session_execution_agent_none_skips_execute() -> None:
    sched = _full_scheduler()
    sched._execution_agent = None

    with patch.object(sched, "_run_investigation", return_value=(_FIXTURE_DECISION, None)):
        sched._process_session(
            run_id=1,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=datetime.now(UTC),
        )

    # No execute call; bank still written
    sched._bank.write_session.assert_called_once()


def test_process_session_no_logger_does_not_raise() -> None:
    sched = _full_scheduler()
    sched._logger = None

    with patch.object(sched, "_run_investigation", return_value=(_FIXTURE_DECISION, None)):
        sched._process_session(
            run_id=1,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=datetime.now(UTC),
        )


def test_investigation_timeout_no_logger_returns_none() -> None:
    sched = _full_scheduler(_investigation_budget_secs=0)
    sched._logger = None
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION
    result = sched._run_investigation("sess-001", datetime.now(UTC), ["SPY", "QQQ"])
    assert result == (None, SessionSkip("SKIPPED_TIMEOUT"))


def test_execute_timeout_no_logger_does_not_raise() -> None:
    sched = _full_scheduler(_execute_budget_secs=0)
    sched._logger = None
    sched._execution_agent.execute.side_effect = lambda *a: time.sleep(0.5)
    # Should not raise
    sched._run_execute(_FIXTURE_DECISION)


def test_run_market_closed_no_logger_does_not_raise() -> None:
    sched = _full_scheduler()
    sched._logger = None
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

    call_count = [0]

    def market_open_side_effect() -> bool:
        call_count[0] += 1
        if call_count[0] == 1:
            return False  # first: closed
        return True  # second: open

    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close"),
        patch.object(sched, "is_market_open", side_effect=market_open_side_effect),
    ):
        sched.run()


# ---------------------------------------------------------------------------
# _run_feedback (T038)
# ---------------------------------------------------------------------------


def _full_scheduler_with_feedback(**extra) -> Scheduler:
    """Build a scheduler with feedback_agent configured."""
    bank = MagicMock()
    bank.start_run.return_value = 1
    bank.get_positions_due_for_feedback.return_value = []
    bank.get_feedback_blocked_tickers.return_value = set()
    cfg = AlphorynConfig(
        tickers=["SPY", "QQQ"],
        candle_timeframe="1H",
        run_duration="1H",
    )
    main_agent = MagicMock()
    main_agent.decide.return_value = _FIXTURE_DECISION
    main_agent.usage = TokenUsage()
    main_agent.model = "gemini-2.5-pro"
    feedback_agent = MagicMock()
    feedback_agent.usage = TokenUsage()
    feedback_agent.model = "gemini-2.5-pro"
    execution_agent = MagicMock()
    # Explicit, not a bare MagicMock: execute() returns the per-ticker
    # execution_result the session record carries (issue #131).
    execution_agent.execute.return_value = {"SPY": "EXECUTED", "QQQ": "EXECUTED"}
    logger = MagicMock()
    return Scheduler(
        cfg,
        bank,
        main_agent=main_agent,
        execution_agent=execution_agent,
        feedback_agent=feedback_agent,
        logger=logger,
        **extra,
    )


def _make_mock_position() -> MagicMock:
    pos = MagicMock()
    pos.id = 99
    pos.session_id = "run-1/session-0001"
    pos.ticker = "SPY"
    pos.strategy = "MEAN_REVERSION"
    pos.entry_price = 450.0
    pos.exit_price = 458.0
    pos.exit_reason = "PROFIT_TARGET"
    return pos


def test_run_feedback_no_feedback_agent_returns_early() -> None:
    sched = _full_scheduler()
    sched._feedback_agent = None
    sched._bank.get_positions_due_for_feedback.return_value = [_make_mock_position()]
    sched._run_feedback("run-1/session-0002")
    sched._bank.get_positions_due_for_feedback.assert_not_called()


def test_run_feedback_queries_bank_for_due_positions() -> None:
    sched = _full_scheduler_with_feedback()
    sched._bank.get_positions_due_for_feedback.return_value = []
    sched._run_feedback("run-1/session-0002")
    assert sched._bank.get_positions_due_for_feedback.call_count == 1
    (now_arg,) = sched._bank.get_positions_due_for_feedback.call_args.args
    assert now_arg.tzinfo is not None  # aware UTC, not a session ordinal


def test_run_feedback_invokes_feedback_agent_per_position() -> None:
    sched = _full_scheduler_with_feedback()
    pos1 = _make_mock_position()
    pos2 = _make_mock_position()
    pos2.id = 100
    pos2.ticker = "QQQ"
    sched._bank.get_positions_due_for_feedback.return_value = [pos1, pos2]
    sched._bank.get_session.return_value = MagicMock(html_report_path="/reports/r.html")

    sched._run_feedback("run-1/session-0002")

    assert sched._feedback_agent.evaluate.call_count == 2


def test_run_feedback_passes_correct_session_id_to_evaluate() -> None:
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    sched._bank.get_session.return_value = MagicMock(html_report_path="/reports/r.html")

    sched._run_feedback("run-1/session-0002")

    call_kwargs = sched._feedback_agent.evaluate.call_args
    assert call_kwargs.args[1] == "run-1/session-0002"


def test_run_feedback_no_positions_does_nothing() -> None:
    sched = _full_scheduler_with_feedback()
    sched._bank.get_positions_due_for_feedback.return_value = []
    sched._run_feedback("run-1/session-0002")
    sched._feedback_agent.evaluate.assert_not_called()


def test_run_feedback_uses_html_report_path_from_session() -> None:
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    mock_session = MagicMock(html_report_path="/reports/run-1/session.html")
    sched._bank.get_session.return_value = mock_session

    sched._run_feedback("run-1/session-0002")

    fi = sched._feedback_agent.evaluate.call_args.args[0]
    assert fi.html_report_path == "/reports/run-1/session.html"


def test_run_feedback_no_entry_session_uses_empty_string_for_path() -> None:
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    sched._bank.get_session.return_value = None  # session not found

    sched._run_feedback("run-1/session-0002")

    fi = sched._feedback_agent.evaluate.call_args.args[0]
    assert fi.html_report_path == ""


# One bad position must not take down the run (issue #164, FR-016a).


def test_run_feedback_carries_on_when_one_position_blows_up() -> None:
    sched = _full_scheduler_with_feedback()
    pos1 = _make_mock_position()
    pos2 = _make_mock_position()
    pos2.id = 100
    pos2.ticker = "QQQ"
    sched._bank.get_positions_due_for_feedback.return_value = [pos1, pos2]
    sched._bank.get_session.return_value = MagicMock(html_report_path="/reports/r.html")
    sched._feedback_agent.evaluate.side_effect = [RuntimeError("boom"), None]

    sched._run_feedback("run-1/session-0002")  # must not raise

    assert sched._feedback_agent.evaluate.call_count == 2


def test_run_feedback_emits_evaluation_failed_for_the_position_that_blew_up() -> None:
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    sched._bank.get_session.return_value = MagicMock(html_report_path="/reports/r.html")
    sched._feedback_agent.evaluate.side_effect = RuntimeError("boom")

    sched._run_feedback("run-1/session-0002")

    failed = [
        c for c in sched._logger.emit.call_args_list if c.args[0] == "EVALUATION_FAILED"
    ]
    assert len(failed) == 1
    assert failed[0].args[2]["position_id"] == 99
    assert "boom" in failed[0].args[2]["error"]
    assert failed[0].kwargs["etf"] == "SPY"


def test_run_feedback_survives_a_blow_up_without_a_logger() -> None:
    sched = _full_scheduler_with_feedback()
    sched._logger = None
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    sched._bank.get_session.return_value = MagicMock(html_report_path="/reports/r.html")
    sched._feedback_agent.evaluate.side_effect = RuntimeError("boom")

    sched._run_feedback("run-1/session-0002")  # must not raise


def test_process_session_calls_run_feedback_before_investigation() -> None:
    sched = _full_scheduler_with_feedback()

    call_order = []

    def mock_feedback(*args):
        call_order.append("feedback")

    def mock_investigation(*args, **kwargs):
        call_order.append("investigation")
        return _FIXTURE_DECISION, None

    with (
        patch.object(sched, "_run_feedback", side_effect=mock_feedback),
        patch.object(sched, "_run_investigation", side_effect=mock_investigation),
    ):
        sched._process_session(
            run_id=1,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=datetime.now(UTC),
        )

    assert call_order == ["feedback", "investigation"]


# ---------------------------------------------------------------------------
# Null strategy guard — issue #88
# ---------------------------------------------------------------------------


def test_process_session_null_strategy_skips_memory_write() -> None:
    """AssetDecision with strategy=None must not attempt a DB write (NOT NULL guard)."""
    sched = _full_scheduler()
    null_strategy_decision = SessionDecision(
        session_id="run-1/session-0001",
        decisions=[
            AssetDecision(
                ticker="SPY",
                action="HOLD",
                strategy=None,  # type: ignore[arg-type]
                lot_size=None,
                exit_target=None,
                reasoning="No regime qualified.",
            ),
            AssetDecision(
                ticker="QQQ",
                action="HOLD",
                strategy="MOMENTUM",
                lot_size=None,
                exit_target=None,
                reasoning="Regime present but no entry signal.",
            ),
        ],
    )

    with patch.object(sched, "_run_investigation", return_value=(null_strategy_decision, None)):
        sched._process_session(
            run_id=1,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=datetime.now(UTC),
        )

    # Only QQQ (strategy="MOMENTUM") should be written; SPY (strategy=None) skipped
    calls = sched._bank.write_memory_entry.call_args_list
    assert len(calls) == 1
    written_entry = calls[0].args[0]
    assert written_entry.ticker == "QQQ"
    assert written_entry.strategy == "MOMENTUM"


# ---------------------------------------------------------------------------
# Position monitor lifecycle (issue #120)
# ---------------------------------------------------------------------------


def _monitored_scheduler(**extra) -> tuple[Scheduler, MagicMock, threading.Event]:
    """Build a full scheduler wired to a mock monitor with nothing left open.

    The mock is spec'd against PositionMonitor, so any attempt by the scheduler
    to call a method the monitor does not have — set_session_ordinal, removed in
    #122 — raises AttributeError rather than silently passing.
    """
    monitor = MagicMock(spec=PositionMonitor)
    stop_event = threading.Event()
    sched = _full_scheduler(monitor=monitor, monitor_stop_event=stop_event, **extra)
    sched._bank.load_open_positions.return_value = []
    return sched, monitor, stop_event


def test_run_starts_monitor_before_first_session() -> None:
    sched, monitor, _ = _monitored_scheduler()
    _run_with_no_wait(sched)
    monitor.start.assert_called_once()


def test_monitor_has_no_session_ordinal_api() -> None:
    """Window expiry is driven by each position's own deadline (issue #122)."""
    assert not hasattr(PositionMonitor, "set_session_ordinal")


def test_run_stops_monitor_when_nothing_is_open() -> None:
    sched, monitor, stop_event = _monitored_scheduler()
    _run_with_no_wait(sched)
    assert stop_event.is_set()
    monitor.join.assert_called_once()


def test_run_ends_run_before_stopping_monitor() -> None:
    sched, _monitor, _ = _monitored_scheduler()
    _run_with_no_wait(sched)
    sched._bank.end_run.assert_called_once_with(1)


def test_start_monitor_emits_telemetry() -> None:
    sched, _monitor, _ = _monitored_scheduler()
    sched._start_monitor()
    events = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "MONITOR_STARTED" in events


def test_start_monitor_without_logger_does_not_raise() -> None:
    sched, monitor, _ = _monitored_scheduler()
    sched._logger = None
    sched._start_monitor()
    monitor.start.assert_called_once()


def test_start_monitor_is_noop_without_monitor() -> None:
    sched = _full_scheduler()
    sched._start_monitor()  # must not raise


def test_stop_monitor_emits_telemetry() -> None:
    sched, _monitor, _ = _monitored_scheduler()
    sched._stop_monitor()
    events = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "MONITOR_STOPPED" in events


def test_stop_monitor_without_logger_does_not_raise() -> None:
    sched, monitor, stop_event = _monitored_scheduler()
    sched._logger = None
    sched._stop_monitor()
    assert stop_event.is_set()
    monitor.join.assert_called_once()


def test_stop_monitor_without_stop_event_still_joins() -> None:
    sched, monitor, _ = _monitored_scheduler()
    sched._monitor_stop_event = None
    sched._stop_monitor()
    monitor.join.assert_called_once()


def test_stop_monitor_is_noop_without_monitor() -> None:
    sched = _full_scheduler()
    sched._stop_monitor()  # must not raise


def test_drain_is_noop_without_monitor() -> None:
    sched = _full_scheduler()
    sched._bank.load_open_positions.return_value = [MagicMock()]
    with patch.object(sched, "wait_for_candle_close") as mock_wait:
        sched._drain_open_positions()
    mock_wait.assert_not_called()


def test_drain_returns_immediately_when_nothing_open() -> None:
    sched, _monitor, _ = _monitored_scheduler()
    with patch.object(sched, "wait_for_candle_close") as mock_wait:
        sched._drain_open_positions()
    mock_wait.assert_not_called()


def test_drain_waits_candle_by_candle_until_positions_close() -> None:
    sched, _monitor, _ = _monitored_scheduler()
    pos = MagicMock()
    sched._bank.load_open_positions.side_effect = [[pos], [pos], [pos], []]
    mock_target = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

    with (
        patch.object(sched, "compute_next_candle_close", return_value=mock_target),
        patch.object(sched, "wait_for_candle_close") as mock_wait,
    ):
        sched._drain_open_positions()

    assert mock_wait.call_count == 2


def test_run_holds_process_open_while_positions_remain() -> None:
    sched, _monitor, stop_event = _monitored_scheduler()
    pos = MagicMock()
    # Session loop never queries open positions; only the drain does.
    sched._bank.load_open_positions.side_effect = [[pos], [pos], []]

    _run_with_no_wait(sched)

    assert stop_event.is_set()


# ---------------------------------------------------------------------------
# Feedback-blocking gates investigation — FR-005 / FR-014 (issue #124)
# ---------------------------------------------------------------------------


def _blocking_scheduler(blocked: set[str], **extra) -> Scheduler:
    sched = _full_scheduler_with_feedback(**extra)
    sched._bank.get_feedback_blocked_tickers.return_value = blocked
    return sched


def _decision_for(*tickers: str) -> SessionDecision:
    return SessionDecision(
        session_id="run-1/session-0001",
        decisions=[
            AssetDecision(
                ticker=t,
                action="BUY",
                strategy="MOMENTUM",
                lot_size=5,
                exit_target={"type": "trailing_stop", "trail_pct": 0.015},
                reasoning="signal",
            )
            for t in tickers
        ],
    )


def test_blocked_ticker_is_kept_out_of_the_investigation_call() -> None:
    """FR-005: no Investigation Agent call is made for a blocked ticker."""
    sched = _blocking_scheduler({"SPY"})
    with patch.object(
        sched, "_run_investigation", return_value=(_decision_for("QQQ"), None)
    ) as mock_investigation:
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    assert mock_investigation.call_args.args[2] == ["QQQ"]


def test_unblocked_tickers_are_all_investigated() -> None:
    sched = _blocking_scheduler(set())
    with patch.object(
        sched, "_run_investigation", return_value=(_decision_for("SPY", "QQQ"), None)
    ) as mock_investigation:
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    assert mock_investigation.call_args.args[2] == ["SPY", "QQQ"]


def test_all_tickers_blocked_skips_the_investigation_entirely() -> None:
    sched = _blocking_scheduler({"SPY", "QQQ"})
    with patch.object(
        sched, "_run_investigation", return_value=(None, "SKIPPED_TIMEOUT")
    ) as mock_investigation:
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    mock_investigation.assert_not_called()
    sched._main_agent.decide.assert_not_called()


def test_blocked_ticker_outcome_is_recorded_as_hold() -> None:
    """FR-005: the blocked ticker's session outcome is still recorded, as Hold."""
    sched = _blocking_scheduler({"SPY"})
    with patch.object(sched, "_run_investigation", return_value=(_decision_for("QQQ"), None)):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    written = sched._bank.write_session.call_args.args[0]
    recorded = json.loads(written.ticker_decisions)
    assert recorded["SPY"] == {
        "strategy": None,
        "decision": "HOLD",
        "execution_result": "EXECUTED",
    }
    assert recorded["QQQ"]["decision"] == "BUY"


def test_session_record_carries_the_execution_result_per_ticker() -> None:
    """Issue #131 / data-model.md: ticker_decisions omitted execution_result entirely."""
    sched = _blocking_scheduler(set())
    sched._execution_agent.execute.return_value = {"SPY": "EXECUTED", "QQQ": "FAILED"}
    with patch.object(
        sched, "_run_investigation", return_value=(_decision_for("SPY", "QQQ"), None)
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    recorded = json.loads(sched._bank.write_session.call_args.args[0].ticker_decisions)
    assert recorded["SPY"]["execution_result"] == "EXECUTED"
    assert recorded["QQQ"]["execution_result"] == "FAILED"


def test_blocked_ticker_is_recorded_as_a_session_warning() -> None:
    """Issue #131 / FR-011: Session.warnings was always NULL."""
    sched = _blocking_scheduler({"SPY"})
    with patch.object(sched, "_run_investigation", return_value=(_decision_for("QQQ"), None)):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    warnings = json.loads(sched._bank.write_session.call_args.args[0].warnings)
    assert any("SPY" in w and "feedback-blocked" in w for w in warnings)


def test_a_clean_session_records_no_warnings() -> None:
    sched = _blocking_scheduler(set())
    with patch.object(
        sched, "_run_investigation", return_value=(_decision_for("SPY", "QQQ"), None)
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    assert sched._bank.write_session.call_args.args[0].warnings is None


def test_a_skipped_session_records_why_as_a_warning() -> None:
    sched = _blocking_scheduler(set())
    with patch.object(
        sched, "_run_investigation", return_value=(None, SessionSkip("SKIPPED_DATA_UNAVAILABLE"))
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    warnings = json.loads(sched._bank.write_session.call_args.args[0].warnings)
    assert warnings == ["Session not completed: SKIPPED_DATA_UNAVAILABLE."]


def test_a_skipped_session_records_the_exception_text_in_the_bank() -> None:
    """The cause must be readable from the bank alone, not only from stdout.

    Without this the 2026-08-13 post-mortem had to go to the run log to learn
    that a 'data unavailable' session was really a model failure.
    """
    sched = _blocking_scheduler(set())
    skip = SessionSkip("SKIPPED_AGENT_ERROR", "main_agent produced no final response")
    with patch.object(sched, "_run_investigation", return_value=(None, skip)):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    warnings = json.loads(sched._bank.write_session.call_args.args[0].warnings)
    assert warnings == [
        "Session not completed: SKIPPED_AGENT_ERROR.",
        "Cause: main_agent produced no final response",
    ]


def test_a_ticker_the_investigation_dropped_is_recorded_as_a_warning() -> None:
    sched = _blocking_scheduler(set())
    with patch.object(sched, "_run_investigation", return_value=(_decision_for("SPY"), None)):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    warnings = json.loads(sched._bank.write_session.call_args.args[0].warnings)
    assert warnings == ["QQQ: investigated but no decision returned; recorded Hold."]


def test_a_ticker_the_agent_invented_is_recorded_as_a_warning() -> None:
    sched = _blocking_scheduler(set())
    with patch.object(
        sched, "_run_investigation", return_value=(_decision_for("SPY", "QQQ", "IWM"), None)
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    warnings = json.loads(sched._bank.write_session.call_args.args[0].warnings)
    assert warnings == ["IWM: not a configured ticker, but the agent returned it."]


def test_an_execute_budget_overrun_is_recorded_as_a_warning() -> None:
    sched = _blocking_scheduler(set(), _execute_budget_secs=0)
    sched._execution_agent.execute.side_effect = lambda *a: time.sleep(0.5) or {}
    with patch.object(
        sched, "_run_investigation", return_value=(_decision_for("SPY", "QQQ"), None)
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    warnings = json.loads(sched._bank.write_session.call_args.args[0].warnings)
    assert warnings == ["Execution budget of 0s exceeded."]


def test_blocked_ticker_is_not_sent_to_the_execution_agent_as_a_buy() -> None:
    sched = _blocking_scheduler({"SPY"})
    with patch.object(sched, "_run_investigation", return_value=(_decision_for("QQQ"), None)):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    executed = sched._execution_agent.execute.call_args.args[0]
    spy = next(d for d in executed.decisions if d.ticker == "SPY")
    assert spy.action == "HOLD"


def test_blocked_ticker_emits_telemetry() -> None:
    sched = _blocking_scheduler({"SPY"})
    with patch.object(sched, "_run_investigation", return_value=(_decision_for("QQQ"), None)):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    blocked_events = [
        c for c in sched._logger.emit.call_args_list if c.args[0] == "TICKER_BLOCKED"
    ]
    assert len(blocked_events) == 1
    assert blocked_events[0].kwargs["etf"] == "SPY"


def test_blocked_tickers_outside_the_config_are_ignored() -> None:
    """A stale position on a ticker no longer configured must not affect the session."""
    sched = _blocking_scheduler({"IWM"})
    with patch.object(
        sched, "_run_investigation", return_value=(_decision_for("SPY", "QQQ"), None)
    ) as mock_investigation:
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    assert mock_investigation.call_args.args[2] == ["SPY", "QQQ"]
    blocked_events = [
        c for c in sched._logger.emit.call_args_list if c.args[0] == "TICKER_BLOCKED"
    ]
    assert blocked_events == []


def test_blocked_tickers_without_logger_does_not_raise() -> None:
    sched = _blocking_scheduler({"SPY"})
    sched._logger = None
    assert sched._blocked_tickers("run-1/session-0001") == {"SPY"}


def test_merge_restores_configured_ticker_order() -> None:
    sched = _blocking_scheduler({"SPY"})
    merged, _ = sched._merge_blocked_holds(_decision_for("QQQ"), {"SPY"})
    assert [d.ticker for d in merged.decisions] == ["SPY", "QQQ"]


def test_merge_holds_a_ticker_the_agent_silently_dropped() -> None:
    sched = _blocking_scheduler(set())
    merged, _ = sched._merge_blocked_holds(_decision_for("SPY"), set())
    qqq = next(d for d in merged.decisions if d.ticker == "QQQ")
    assert qqq.action == "HOLD"
    assert "No decision returned" in qqq.reasoning


def test_merge_keeps_a_ticker_the_agent_invented() -> None:
    sched = _blocking_scheduler(set())
    merged, _ = sched._merge_blocked_holds(_decision_for("SPY", "QQQ", "IWM"), set())
    assert [d.ticker for d in merged.decisions] == ["SPY", "QQQ", "IWM"]


def test_timed_out_investigation_is_not_merged() -> None:
    """A budget timeout must still record SKIPPED_TIMEOUT, not a wall of Holds."""
    sched = _blocking_scheduler({"SPY"})
    with patch.object(
        sched, "_run_investigation", return_value=(None, SessionSkip("SKIPPED_TIMEOUT"))
    ):
        sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    written = sched._bank.write_session.call_args.args[0]
    assert written.status == "SKIPPED_TIMEOUT"


# ---------------------------------------------------------------------------
# Memory read-back — FR-008a (issue #128)
# ---------------------------------------------------------------------------


def _memory_entry(
    ticker: str,
    *,
    strategy: str = "MOMENTUM",
    decision: str = "BUY",
    outcome_judgment: str | None = "CORRECT",
) -> MagicMock:
    entry = MagicMock()
    entry.ticker = ticker
    entry.strategy = strategy
    entry.session_id = "run-1/session-0001"
    entry.decision = decision
    entry.outcome_judgment = outcome_judgment
    entry.regime_context = '{"session_ordinal": 1}'
    entry.created_at = datetime(2024, 1, 15, 15, 0, tzinfo=UTC)
    return entry


def test_recent_memory_serialises_every_field_the_skill_reads() -> None:
    sched = _full_scheduler()
    sched._bank.get_recent_memory_entries.return_value = [_memory_entry("SPY")]

    assert sched._recent_memory(["SPY"]) == [
        {
            "ticker": "SPY",
            "strategy": "MOMENTUM",
            "session_id": "run-1/session-0001",
            "decision": "BUY",
            "outcome_judgment": "CORRECT",
            "regime_context": '{"session_ordinal": 1}',
            "created_at": "2024-01-15T15:00:00+00:00",
        }
    ]


def test_recent_memory_covers_every_investigated_ticker() -> None:
    sched = _full_scheduler()
    sched._bank.get_recent_memory_entries.side_effect = lambda t: [_memory_entry(t)]

    assert [e["ticker"] for e in sched._recent_memory(["SPY", "QQQ"])] == ["SPY", "QQQ"]


def test_investigation_is_given_the_memory_entries() -> None:
    """FR-008a: on main the bank was written and never read back."""
    sched = _full_scheduler()
    sched._bank.get_recent_memory_entries.side_effect = lambda t: [_memory_entry(t)]

    _run_with_no_wait(sched)

    memory_arg = sched._main_agent.decide.call_args.args[3]
    assert [e["ticker"] for e in memory_arg] == ["SPY", "QQQ"]


def test_blocked_tickers_contribute_no_memory_to_the_investigation() -> None:
    """Only the tickers actually investigated are looked up."""
    sched = _blocking_scheduler({"SPY"})
    sched._bank.get_recent_memory_entries.side_effect = lambda t: [_memory_entry(t)]

    sched._process_session(1, "run-1/session-0001", 1, datetime.now(UTC))

    memory_arg = sched._main_agent.decide.call_args.args[3]
    assert [e["ticker"] for e in memory_arg] == ["QQQ"]


# ---------------------------------------------------------------------------
# Feedback input carries the evaluation timestamp (issue #129)
# ---------------------------------------------------------------------------


def test_feedback_input_carries_the_evaluation_window_deadline() -> None:
    """FR-016: the feedback agent needs the timestamp to price the candle at."""
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    pos.evaluation_window_close_at = datetime(2024, 1, 15, 19, 0)
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    sched._bank.get_session.return_value = MagicMock(
        html_report_path="reports/run-1/session-0001.html"
    )

    sched._run_feedback("run-1/session-0005")

    feedback_input = sched._feedback_agent.evaluate.call_args.args[0]
    assert feedback_input.evaluation_window_close_at == datetime(
        2024, 1, 15, 19, 0, tzinfo=UTC
    )


# ---------------------------------------------------------------------------
# FR-018 Session budget counting & try/finally cleanup
# ---------------------------------------------------------------------------


def test_skipped_sessions_do_not_count_against_session_budget() -> None:
    """FR-018: SKIPPED_TIMEOUT and SKIPPED_DATA_UNAVAILABLE do not increment completed count."""
    # session_count is derived (run_duration 1H / candle 1H = 1), not assignable.
    sched = _full_scheduler()
    call_count = 0

    def mock_investigation(*args: Any, **kwargs: Any) -> tuple[Any, SessionSkip | None]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None, SessionSkip("SKIPPED_TIMEOUT")
        return _decision_for("SPY"), None

    with patch.object(sched, "_run_investigation", side_effect=mock_investigation):
        _run_with_no_wait(sched)

    # 1 timeout skip + 1 completed session = 2 total attempts to hit session_count=1
    assert call_count == 2
    assert sched._bank.write_session.call_count == 2


def test_run_finally_cleans_up_on_keyboard_interrupt() -> None:
    """Aborting during the run loop must still execute end_run, drain, and stop_monitor."""
    stop_event = MagicMock()
    monitor = MagicMock()
    sched = _full_scheduler(monitor=monitor, monitor_stop_event=stop_event)
    with patch.object(sched, "_process_session", side_effect=KeyboardInterrupt):
        try:
            _run_with_no_wait(sched)
        except KeyboardInterrupt:
            pass

    sched._bank.end_run.assert_called_once()
    stop_event.set.assert_called_once()
    monitor.join.assert_called_once()


def test_handle_overrun_candles_records_skipped_sessions() -> None:
    """SC-003: intermediate closed candles passed during long session processing
    are recorded as skipped.
    """
    sched = _full_scheduler()
    last_close = datetime(2024, 1, 15, 14, 0, tzinfo=UTC)
    next_close = datetime(2024, 1, 15, 17, 0, tzinfo=UTC)
    mock_now = datetime(2024, 1, 15, 16, 30, tzinfo=UTC)

    with patch("alphoryn.scheduler.scheduler.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        new_ordinal = sched._handle_overrun_candles(1, last_close, next_close, session_ordinal=2)

    # Missed 15:00 and 16:00 boundaries -> ordinal advances by 2 (from 2 to 4)
    assert new_ordinal == 4
    assert sched._bank.write_session.call_count == 2
    session_statuses = [
        call.args[0].status for call in sched._bank.write_session.call_args_list
    ]
    assert all(s in ("SKIPPED_OVERRUN", "SKIPPED_MARKET_CLOSED") for s in session_statuses)


def test_handle_overrun_candles_uses_skipped_overrun_when_the_market_is_open() -> None:
    """The data was fine, we were busy - so not SKIPPED_DATA_UNAVAILABLE (issue #169)."""
    sched = _full_scheduler()
    last_close = datetime(2024, 1, 15, 14, 0, tzinfo=UTC)
    next_close = datetime(2024, 1, 15, 17, 0, tzinfo=UTC)
    mock_now = datetime(2024, 1, 15, 16, 30, tzinfo=UTC)

    with (
        patch("alphoryn.scheduler.scheduler.datetime") as mock_datetime,
        patch.object(sched, "is_market_open", return_value=True),
    ):
        mock_datetime.now.return_value = mock_now
        sched._handle_overrun_candles(1, last_close, next_close, session_ordinal=2)

    statuses = [c.args[0].status for c in sched._bank.write_session.call_args_list]
    assert statuses == ["SKIPPED_OVERRUN", "SKIPPED_OVERRUN"]


def test_handle_overrun_candles_still_says_market_closed_when_it_is() -> None:
    sched = _full_scheduler()
    last_close = datetime(2024, 1, 15, 14, 0, tzinfo=UTC)
    next_close = datetime(2024, 1, 15, 17, 0, tzinfo=UTC)
    mock_now = datetime(2024, 1, 15, 16, 30, tzinfo=UTC)

    with (
        patch("alphoryn.scheduler.scheduler.datetime") as mock_datetime,
        patch.object(sched, "is_market_open", return_value=False),
    ):
        mock_datetime.now.return_value = mock_now
        sched._handle_overrun_candles(1, last_close, next_close, session_ordinal=2)

    statuses = [c.args[0].status for c in sched._bank.write_session.call_args_list]
    assert statuses == ["SKIPPED_MARKET_CLOSED", "SKIPPED_MARKET_CLOSED"]



# ---------------------------------------------------------------------------
# Token usage summary at end of run
# ---------------------------------------------------------------------------


def _usage(**kwargs) -> TokenUsage:
    return TokenUsage(**kwargs)


def test_run_prints_what_each_agent_and_the_run_spent() -> None:
    sched = _full_scheduler_with_feedback()
    sched._main_agent.model = "gemini-2.5-pro"
    sched._main_agent.usage = _usage(calls=10, input_tokens=1_000_000, output_tokens=100_000)
    sched._feedback_agent.model = "gemini-2.5-flash"
    sched._feedback_agent.usage = _usage(calls=2, input_tokens=1_000_000)

    buf = StringIO()
    with patch("sys.stdout", buf):
        sched._report_token_usage()

    out = buf.getvalue()
    assert "gemini-2.5-pro" in out
    assert "gemini-2.5-flash" in out
    # pro: 1.25 + 1.00 = 2.25   flash: 0.30   run total: 2.55
    assert "~$2.25" in out
    assert "~$0.30" in out
    assert "Run " in out and "~$2.55" in out


def test_the_run_total_is_summed_per_model_not_priced_at_one_rate() -> None:
    """Pricing a mixed total at one model's rate is how a cost report starts lying."""
    sched = _full_scheduler_with_feedback()
    sched._main_agent.model = "gemini-2.5-pro"
    sched._main_agent.usage = _usage(calls=1, output_tokens=1_000_000)  # $10.00
    sched._feedback_agent.model = "gemini-2.5-flash-lite"
    sched._feedback_agent.usage = _usage(calls=1, output_tokens=1_000_000)  # $0.40

    buf = StringIO()
    with patch("sys.stdout", buf):
        sched._report_token_usage()

    assert "~$10.40" in buf.getvalue()  # not 2 x pro ($20) and not 2 x lite ($0.80)


def test_a_run_that_never_called_the_model_prints_no_run_total() -> None:
    sched = _full_scheduler_with_feedback()
    sched._main_agent.model = "gemini-2.5-pro"
    sched._main_agent.usage = TokenUsage()
    sched._feedback_agent.model = "gemini-2.5-pro"
    sched._feedback_agent.usage = TokenUsage()

    buf = StringIO()
    with patch("sys.stdout", buf):
        sched._report_token_usage()

    assert "Run " not in buf.getvalue()


def test_usage_is_reported_without_agents_configured() -> None:
    """Startup-only mode has no agents to bill; the summary must not blow up."""
    sched = _scheduler()
    buf = StringIO()
    with patch("sys.stdout", buf):
        sched._report_token_usage()
    assert buf.getvalue() == ""


def test_an_unpriced_model_still_reports_its_tokens() -> None:
    sched = _full_scheduler_with_feedback()
    sched._main_agent.model = "gemini-99-unreleased"
    sched._main_agent.usage = _usage(calls=1, input_tokens=500)
    sched._feedback_agent.model = "gemini-99-unreleased"
    sched._feedback_agent.usage = TokenUsage()

    buf = StringIO()
    with patch("sys.stdout", buf):
        sched._report_token_usage()

    out = buf.getvalue()
    assert "cost unknown" in out
    assert "500 in" in out
