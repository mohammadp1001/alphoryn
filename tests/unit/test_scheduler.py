"""Unit tests for alphoryn/scheduler/scheduler.py (T016 scope)."""

from datetime import UTC, datetime
from io import StringIO
from unittest.mock import MagicMock, patch

from alphoryn.config.models import AlphorynConfig
from alphoryn.scheduler.scheduler import Scheduler

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cfg(**kwargs) -> AlphorynConfig:
    defaults = {
        "etf1": "SPY",
        "etf2": "QQQ",
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
    mock_tc_cls = MagicMock(return_value=mock_client)
    mock_alpaca = MagicMock()
    mock_alpaca.TradingClient = mock_tc_cls
    mock_trading_mod = MagicMock()
    mock_trading_mod.TradingClient = mock_tc_cls

    with patch.dict(
        "sys.modules",
        {
            "alpaca": MagicMock(),
            "alpaca.trading": MagicMock(),
            "alpaca.trading.client": mock_trading_mod,
        },
    ):
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


def test_wait_for_candle_close_sleeps_in_10s_increments() -> None:
    sched = _scheduler(max_startup_latency_seconds=3600)
    future = datetime(2024, 1, 15, 16, 0, 0, tzinfo=UTC)

    times = [
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

    # All sleep durations must be ≤ 10
    assert all(s <= 10.0 for s in sleep_args)
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
