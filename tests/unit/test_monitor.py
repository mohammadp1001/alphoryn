"""Unit tests for alphoryn/monitor/monitor.py (T032 scope).

All tests use stub/mock dependencies — zero LLM calls asserted via
PositionMonitor.model == None (Principle I).
"""

import json
import threading
from unittest.mock import MagicMock, patch

from alphoryn.memory.schema import Position
from alphoryn.monitor.monitor import PositionMonitor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_position(
    *,
    pos_id: int = 1,
    etf: str = "SPY",
    stop_loss_price: float = 440.0,
    exit_target: dict | None = None,
    strategy: str = "MEAN_REVERSION",
    evaluation_window_session: int = 10,
    session_id: str = "run-1/session-001",
    trailing_stop_high_watermark: float | None = None,
) -> Position:
    if exit_target is None:
        exit_target = {"type": "price_level", "value": 460.0}
    pos = Position()
    pos.id = pos_id
    pos.etf = etf
    pos.stop_loss_price = stop_loss_price
    pos.exit_target = json.dumps(exit_target)
    pos.strategy = strategy
    pos.evaluation_window_session = evaluation_window_session
    pos.status = "OPEN"
    pos.session_id = session_id
    pos.trailing_stop_high_watermark = trailing_stop_high_watermark
    pos.entry_price = 450.0
    pos.lot_size = 5.0
    pos.direction = "BUY"
    return pos


def _make_monitor(
    *,
    current_session_ordinal: int = 1,
    stop_event: threading.Event | None = None,
    poll_interval: float = 30.0,
) -> tuple[PositionMonitor, MagicMock, MagicMock, MagicMock]:
    bank = MagicMock()
    market_data = MagicMock()
    logger = MagicMock()
    if stop_event is None:
        stop_event = threading.Event()
    monitor = PositionMonitor(
        bank=bank,
        market_data=market_data,
        logger=logger,
        current_session_ordinal=current_session_ordinal,
        stop_event=stop_event,
        poll_interval=poll_interval,
    )
    return monitor, bank, market_data, logger


# ---------------------------------------------------------------------------
# Constitution Principle I
# ---------------------------------------------------------------------------


def test_model_attribute_is_none() -> None:
    monitor, _, _, _ = _make_monitor()
    assert monitor.model is None


def test_class_model_attribute_is_none() -> None:
    assert PositionMonitor.model is None


# ---------------------------------------------------------------------------
# Stop-loss
# ---------------------------------------------------------------------------


def test_stop_loss_calls_update_position_close() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(stop_loss_price=440.0)
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 439.0  # below stop-loss

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_called_once()
    call_kwargs = bank.update_position_close.call_args.kwargs
    assert call_kwargs["status"] == "CLOSED_STOP_LOSS"
    assert call_kwargs["exit_reason"] == "STOP_LOSS"


def test_stop_loss_at_exact_price_triggers() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(stop_loss_price=440.0)
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 440.0  # exactly at stop

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_called_once()


def test_stop_loss_emits_stop_loss_triggered() -> None:
    monitor, bank, market_data, logger = _make_monitor()
    pos = _make_position(stop_loss_price=440.0)
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 430.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "STOP_LOSS_TRIGGERED" in emitted_types


def test_stop_loss_emits_position_closed() -> None:
    monitor, bank, market_data, logger = _make_monitor()
    pos = _make_position(stop_loss_price=440.0)
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 430.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "POSITION_CLOSED" in emitted_types


# ---------------------------------------------------------------------------
# Profit-target (price_level)
# ---------------------------------------------------------------------------


def test_price_level_target_reached_closes_position() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 460.0},
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 461.0  # above target

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_called_once()
    assert bank.update_position_close.call_args.kwargs["status"] == "CLOSED_PROFIT_TARGET"


def test_price_level_exact_target_triggers() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 460.0},
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 460.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_called_once()


def test_price_level_target_emits_profit_target_triggered() -> None:
    monitor, bank, market_data, logger = _make_monitor()
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 460.0},
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 465.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "PROFIT_TARGET_TRIGGERED" in emitted_types


# ---------------------------------------------------------------------------
# Window expiry
# ---------------------------------------------------------------------------


def test_window_expiry_closes_position_on_matching_ordinal() -> None:
    monitor, bank, market_data, _ = _make_monitor(current_session_ordinal=5)
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 480.0},
        evaluation_window_session=5,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 450.0  # between stop and target

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_called_once()
    assert bank.update_position_close.call_args.kwargs["status"] == "CLOSED_WINDOW_EXPIRY"


def test_window_expiry_emits_window_expiry_triggered() -> None:
    monitor, bank, market_data, logger = _make_monitor(current_session_ordinal=5)
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 480.0},
        evaluation_window_session=5,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 450.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "WINDOW_EXPIRY_TRIGGERED" in emitted_types


def test_window_ordinal_not_matched_does_not_close() -> None:
    monitor, bank, market_data, _ = _make_monitor(current_session_ordinal=3)
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 480.0},
        evaluation_window_session=5,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 450.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_not_called()


# ---------------------------------------------------------------------------
# Trailing stop (Momentum)
# ---------------------------------------------------------------------------


def test_trailing_stop_new_high_updates_watermark() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        trailing_stop_high_watermark=None,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 462.0  # new high

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_trailing_watermark.assert_called_once_with(1, 462.0)
    bank.update_position_close.assert_not_called()  # stop not hit at 462 vs 462*(1-0.015)=455.6


def test_trailing_stop_existing_watermark_above_price_preserved() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        trailing_stop_high_watermark=500.0,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 498.0  # below watermark, above stop

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_trailing_watermark.assert_not_called()  # watermark stays at 500
    bank.update_position_close.assert_not_called()  # 498 > 500*(1-0.015)=492.5


def test_trailing_stop_hit_closes_position() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        trailing_stop_high_watermark=500.0,
    )
    bank.load_open_positions.return_value = [pos]
    # stop_price = 500 * (1 - 0.015) = 492.5; current < stop_price
    market_data.get_latest_price.return_value = 490.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_called_once()
    assert bank.update_position_close.call_args.kwargs["status"] == "CLOSED_PROFIT_TARGET"


def test_trailing_stop_hit_emits_profit_target_triggered() -> None:
    monitor, bank, market_data, logger = _make_monitor()
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        trailing_stop_high_watermark=500.0,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 490.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    emitted_types = [c.args[0] for c in logger.emit.call_args_list]
    assert "PROFIT_TARGET_TRIGGERED" in emitted_types


# ---------------------------------------------------------------------------
# Alpaca close_position failure (retry next poll)
# ---------------------------------------------------------------------------


def test_alpaca_failure_does_not_call_update_position_close() -> None:
    monitor, bank, market_data, _ = _make_monitor()
    pos = _make_position(stop_loss_price=440.0)
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 430.0

    with patch("alphoryn.monitor.monitor.TradingClient") as mock_tc_cls:
        mock_tc = MagicMock()
        mock_tc_cls.return_value = mock_tc
        mock_tc.close_position.side_effect = RuntimeError("API error")
        monitor._check_positions()

    bank.update_position_close.assert_not_called()


def test_alpaca_failure_does_not_emit_telemetry() -> None:
    monitor, bank, market_data, logger = _make_monitor()
    pos = _make_position(stop_loss_price=440.0)
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 430.0

    with patch("alphoryn.monitor.monitor.TradingClient") as mock_tc_cls:
        mock_tc = MagicMock()
        mock_tc_cls.return_value = mock_tc
        mock_tc.close_position.side_effect = RuntimeError("API error")
        monitor._check_positions()

    logger.emit.assert_not_called()


# ---------------------------------------------------------------------------
# No-action paths
# ---------------------------------------------------------------------------


def test_no_open_positions_does_nothing() -> None:
    monitor, bank, market_data, logger = _make_monitor()
    bank.load_open_positions.return_value = []

    monitor._check_positions()

    market_data.get_latest_price.assert_not_called()
    logger.emit.assert_not_called()


def test_price_between_stop_and_target_no_close() -> None:
    monitor, bank, market_data, _ = _make_monitor(current_session_ordinal=1)
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 480.0},
        evaluation_window_session=10,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 455.0  # between stop and target

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_not_called()


def test_unknown_exit_target_type_falls_through_to_window_check() -> None:
    monitor, bank, market_data, _ = _make_monitor(current_session_ordinal=1)
    pos = _make_position(
        stop_loss_price=430.0,
        exit_target={"type": "unknown_type", "value": 999.0},
        evaluation_window_session=10,
    )
    bank.load_open_positions.return_value = [pos]
    market_data.get_latest_price.return_value = 450.0

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    bank.update_position_close.assert_not_called()


# ---------------------------------------------------------------------------
# run() loop
# ---------------------------------------------------------------------------


def test_run_exits_when_stop_event_is_set() -> None:
    stop_event = threading.Event()
    stop_event.set()  # stop immediately
    monitor, bank, market_data, _ = _make_monitor(
        stop_event=stop_event, poll_interval=0.01
    )
    bank.load_open_positions.return_value = []

    monitor.run()  # should return quickly

    # If it didn't exit, the test would hang — just assert it returned
    assert True


def test_run_calls_check_positions_before_stopping() -> None:
    stop_event = threading.Event()
    monitor, bank, market_data, _ = _make_monitor(
        stop_event=stop_event, poll_interval=0.01
    )
    bank.load_open_positions.return_value = []
    check_count = [0]

    original_check = monitor._check_positions

    def counting_check() -> None:
        check_count[0] += 1
        stop_event.set()
        original_check()

    monitor._check_positions = counting_check
    monitor.run()

    assert check_count[0] >= 1


# ---------------------------------------------------------------------------
# Daemon thread configuration
# ---------------------------------------------------------------------------


def test_monitor_is_daemon_thread() -> None:
    monitor, _, _, _ = _make_monitor()
    assert monitor.daemon is True
