"""Unit tests for alphoryn/scheduler/scheduler.py (T016 + T029/T030 scope)."""

import threading
import time
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import MagicMock, patch

from alphoryn.config.models import AlphorynConfig
from alphoryn.execution.agent import AssetDecision, SessionDecision
from alphoryn.scheduler.scheduler import Scheduler

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cfg(**kwargs) -> AlphorynConfig:
    defaults = {
        "tickers": ["SPY", "QQQ"],
        "candle_timeframe": "1H",
        "run_duration": "24H",
        "max_startup_latency_seconds": 60,
    }
    defaults.update(kwargs)
    return AlphorynConfig(**defaults)


def _scheduler(**cfg_kwargs) -> Scheduler:
    bank = MagicMock()
    return Scheduler(_cfg(**cfg_kwargs), bank)


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
# next_market_open_close
# ---------------------------------------------------------------------------


def test_next_market_open_close_success() -> None:
    sched = _scheduler()
    mock_clock = MagicMock()
    t_open = datetime(2024, 1, 15, 14, 30, tzinfo=UTC)
    t_close = datetime(2024, 1, 15, 21, 0, tzinfo=UTC)
    mock_clock.next_open = t_open
    mock_clock.next_close = t_close

    with patch.object(sched, "get_market_clock", return_value=mock_clock):
        nxt_open, nxt_close = sched.next_market_open_close()

    assert nxt_open == t_open
    assert nxt_close == t_close


def test_next_market_open_close_api_failure_returns_none_none() -> None:
    sched = _scheduler()
    with patch.object(sched, "get_market_clock", side_effect=RuntimeError("timeout")):
        buf = StringIO()
        with patch("sys.stderr", buf):
            nxt_open, nxt_close = sched.next_market_open_close()
    assert nxt_open is None
    assert nxt_close is None
    assert "WARN" in buf.getvalue()


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


def test_is_market_open_fallback_true_on_api_error() -> None:
    sched = _scheduler()
    with patch.object(sched, "get_market_clock", side_effect=RuntimeError("no conn")):
        assert sched.is_market_open() is True


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
    sched = _scheduler(max_startup_latency_seconds=300)
    future = datetime.now(UTC).replace(microsecond=0)
    # target already passed → immediate exit
    with patch("alphoryn.scheduler.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = future.replace(second=future.second + 1)
        mock_dt.fromtimestamp = datetime.fromtimestamp
        buf = StringIO()
        sleep_calls: list = []
        with patch("sys.stdout", buf):
            sched.wait_for_candle_close(future, _sleep=sleep_calls.append)
    # A countdown line must have been printed (even if wait = 0)
    assert "Waiting for next candle close at" in buf.getvalue()


def test_wait_for_candle_close_warns_on_long_wait() -> None:
    sched = _scheduler(max_startup_latency_seconds=10)
    future = datetime(2024, 1, 15, 16, 0, 0, tzinfo=UTC)

    now_before = datetime(2024, 1, 15, 15, 45, 0, tzinfo=UTC)  # 15 min wait
    now_after = datetime(2024, 1, 15, 16, 0, 1, tzinfo=UTC)   # past target

    call_count = [0]

    def fake_now(tz=None):
        call_count[0] += 1
        return now_before if call_count[0] == 1 else now_after

    with patch("alphoryn.scheduler.scheduler.datetime") as mock_dt:
        mock_dt.now.side_effect = fake_now
        mock_dt.fromtimestamp = datetime.fromtimestamp
        err_buf = StringIO()
        with patch("sys.stderr", err_buf):
            sched.wait_for_candle_close(future, _sleep=lambda _: None)

    assert "WARN" in err_buf.getvalue()
    assert "max_startup_latency_seconds" in err_buf.getvalue()


def test_wait_for_candle_close_no_warn_within_latency() -> None:
    sched = _scheduler(max_startup_latency_seconds=3600)
    future = datetime(2024, 1, 15, 16, 0, 0, tzinfo=UTC)
    now_val = datetime(2024, 1, 15, 15, 59, 0, tzinfo=UTC)  # 60s wait

    call_count = [0]

    def fake_now(tz=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return now_val
        return datetime(2024, 1, 15, 16, 0, 1, tzinfo=UTC)

    with patch("alphoryn.scheduler.scheduler.datetime") as mock_dt:
        mock_dt.now.side_effect = fake_now
        mock_dt.fromtimestamp = datetime.fromtimestamp
        err_buf = StringIO()
        with patch("sys.stderr", err_buf):
            sched.wait_for_candle_close(future, _sleep=lambda _: None)

    assert "WARN" not in err_buf.getvalue()


def test_wait_for_candle_close_sleeps_in_1s_increments() -> None:
    sched = _scheduler(max_startup_latency_seconds=3600)
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
    cfg = AlphorynConfig(
        tickers=["SPY", "QQQ"],
        candle_timeframe="1H",
        run_duration="1H",  # session_count = 1
        max_startup_latency_seconds=3600,
    )
    main_agent = MagicMock()
    main_agent.decide.return_value = _FIXTURE_DECISION
    execution_agent = MagicMock()
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

    # Still processes exactly 1 session (session_count=1)
    sched._bank.write_session.assert_called_once()


# ---------------------------------------------------------------------------
# Budget timeout (T029)
# ---------------------------------------------------------------------------


def test_investigation_timeout_emits_budget_timeout() -> None:
    sched = _full_scheduler(_investigation_budget_secs=0)
    # Make decide() block long enough for timeout
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION

    _run_with_no_wait(sched)

    emitted = [c.args[0] for c in sched._logger.emit.call_args_list]
    assert "BUDGET_TIMEOUT" in emitted


def test_investigation_timeout_writes_skipped_session() -> None:
    sched = _full_scheduler(_investigation_budget_secs=0)
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION

    _run_with_no_wait(sched)

    sched._bank.write_session.assert_called_once()
    session_arg = sched._bank.write_session.call_args.args[0]
    assert session_arg.status == "SKIPPED_TIMEOUT"


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
    result = sched._run_investigation("sess-001", datetime.now(UTC))
    assert result == _FIXTURE_DECISION


def test_run_investigation_returns_none_on_timeout() -> None:
    sched = _full_scheduler(_investigation_budget_secs=0)
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION
    result = sched._run_investigation("sess-001", datetime.now(UTC))
    assert result is None


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
    with patch.object(sched, "_run_investigation", return_value=None):
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

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
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

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
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

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
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

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
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
    result = sched._run_investigation("sess-001", datetime.now(UTC))
    assert result is None


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
    cfg = AlphorynConfig(
        tickers=["SPY", "QQQ"],
        candle_timeframe="1H",
        run_duration="1H",
        max_startup_latency_seconds=3600,
    )
    main_agent = MagicMock()
    main_agent.decide.return_value = _FIXTURE_DECISION
    feedback_agent = MagicMock()
    logger = MagicMock()
    return Scheduler(
        cfg,
        bank,
        main_agent=main_agent,
        execution_agent=MagicMock(),
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
    sched._run_feedback("run-1/session-0002", 2)
    sched._bank.get_positions_due_for_feedback.assert_not_called()


def test_run_feedback_queries_bank_for_due_positions() -> None:
    sched = _full_scheduler_with_feedback()
    sched._bank.get_positions_due_for_feedback.return_value = []
    sched._run_feedback("run-1/session-0002", 2)
    sched._bank.get_positions_due_for_feedback.assert_called_once_with(2)


def test_run_feedback_invokes_feedback_agent_per_position() -> None:
    sched = _full_scheduler_with_feedback()
    pos1 = _make_mock_position()
    pos2 = _make_mock_position()
    pos2.id = 100
    pos2.ticker = "QQQ"
    sched._bank.get_positions_due_for_feedback.return_value = [pos1, pos2]
    sched._bank.get_session.return_value = MagicMock(html_report_path="/reports/r.html")

    sched._run_feedback("run-1/session-0002", 2)

    assert sched._feedback_agent.evaluate.call_count == 2


def test_run_feedback_passes_correct_session_id_to_evaluate() -> None:
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    sched._bank.get_session.return_value = MagicMock(html_report_path="/reports/r.html")

    sched._run_feedback("run-1/session-0002", 2)

    call_kwargs = sched._feedback_agent.evaluate.call_args
    assert call_kwargs.args[1] == "run-1/session-0002"


def test_run_feedback_no_positions_does_nothing() -> None:
    sched = _full_scheduler_with_feedback()
    sched._bank.get_positions_due_for_feedback.return_value = []
    sched._run_feedback("run-1/session-0002", 2)
    sched._feedback_agent.evaluate.assert_not_called()


def test_run_feedback_uses_html_report_path_from_session() -> None:
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    mock_session = MagicMock(html_report_path="/reports/run-1/session.html")
    sched._bank.get_session.return_value = mock_session

    sched._run_feedback("run-1/session-0002", 2)

    fi = sched._feedback_agent.evaluate.call_args.args[0]
    assert fi.html_report_path == "/reports/run-1/session.html"


def test_run_feedback_no_entry_session_uses_empty_string_for_path() -> None:
    sched = _full_scheduler_with_feedback()
    pos = _make_mock_position()
    sched._bank.get_positions_due_for_feedback.return_value = [pos]
    sched._bank.get_session.return_value = None  # session not found

    sched._run_feedback("run-1/session-0002", 2)

    fi = sched._feedback_agent.evaluate.call_args.args[0]
    assert fi.html_report_path == ""


def test_process_session_calls_run_feedback_before_investigation() -> None:
    sched = _full_scheduler_with_feedback()

    call_order = []

    def mock_feedback(*args):
        call_order.append("feedback")

    def mock_investigation(*args, **kwargs):
        call_order.append("investigation")
        return _FIXTURE_DECISION

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

    with patch.object(sched, "_run_investigation", return_value=null_strategy_decision):
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
