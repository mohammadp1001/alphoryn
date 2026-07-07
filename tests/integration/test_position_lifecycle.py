"""Integration test: position lifecycle — T035.

Uses a real SQLite MemoryBank with Alpaca API calls stubbed. Validates:
  - Stop-loss exit closes position and marks status CLOSED_STOP_LOSS
  - Blocked BUY when OPEN position exists on same ticker (FR-014)
  - Trailing stop watermark updated on new price high
  - Window expiry exit closes position with CLOSED_WINDOW_EXPIRY
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DBSession

from alphoryn.execution.agent import AssetDecision, ExecutionAgent, SessionDecision
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position, Session
from alphoryn.monitor.monitor import PositionMonitor
from alphoryn.telemetry.logger import TelemetryLogger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_bank(db_path: Path) -> MemoryBank:
    bank = MemoryBank(str(db_path))
    return bank


def _write_run_and_session(bank: MemoryBank) -> tuple[int, str]:
    run_id = bank.start_run(config_snapshot="{}", session_count_planned=10)
    session_id = f"run-{run_id}/session-001"
    with DBSession(bank._engine) as s:
        sess = Session(
            id=session_id,
            run_id=run_id,
            candle_close_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            status="COMPLETED",
        )
        s.add(sess)
        s.commit()
    return run_id, session_id


def _open_position(
    bank: MemoryBank,
    session_id: str,
    *,
    ticker: str = "SPY",
    strategy: str = "MEAN_REVERSION",
    stop_loss_price: float = 430.0,
    exit_target: dict | None = None,
    evaluation_window_session: int = 10,
    trailing_stop_high_watermark: float | None = None,
) -> int:
    if exit_target is None:
        exit_target = {"type": "price_level", "value": 470.0}
    pos = Position(
        session_id=session_id,
        ticker=ticker,
        strategy=strategy,
        direction="BUY",
        entry_price=450.0,
        entry_time=datetime.now(UTC),
        lot_size=5.0,
        stop_loss_price=stop_loss_price,
        exit_target=json.dumps(exit_target),
        evaluation_window_session=evaluation_window_session,
        trailing_stop_high_watermark=trailing_stop_high_watermark,
        status="OPEN",
    )
    return bank.write_position(pos)


def _make_monitor(
    bank: MemoryBank,
    *,
    current_price: float,
    current_session_ordinal: int = 1,
) -> tuple[PositionMonitor, MagicMock]:
    market_data = MagicMock()
    market_data.get_latest_price.return_value = current_price
    logger = TelemetryLogger.__new__(TelemetryLogger)
    logger._log_name = "test"
    logger._cloud_logger = None
    monitor = PositionMonitor(
        bank=bank,
        market_data=market_data,
        logger=logger,
        current_session_ordinal=current_session_ordinal,
        stop_event=threading.Event(),
    )
    return monitor, market_data


# ---------------------------------------------------------------------------
# Stop-loss exit
# ---------------------------------------------------------------------------


def test_stop_loss_closes_position_in_db(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    _, session_id = _write_run_and_session(bank)
    pos_id = _open_position(bank, session_id, stop_loss_price=440.0)

    monitor, _ = _make_monitor(bank, current_price=435.0)  # below stop-loss

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    # Reload position from DB
    open_positions = bank.load_open_positions()
    assert not any(p.id == pos_id for p in open_positions)


def test_stop_loss_sets_status_closed_stop_loss(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    _, session_id = _write_run_and_session(bank)
    pos_id = _open_position(bank, session_id, stop_loss_price=440.0)

    monitor, _ = _make_monitor(bank, current_price=435.0)

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    with DBSession(bank._engine) as s:
        pos = s.query(Position).filter(Position.id == pos_id).one()
        assert pos.status == "CLOSED_STOP_LOSS"
        assert pos.exit_reason == "STOP_LOSS"
        assert pos.exit_price == 435.0
        assert pos.exit_time is not None


# ---------------------------------------------------------------------------
# BUY blocked when OPEN position exists (FR-014)
# ---------------------------------------------------------------------------


def test_buy_blocked_by_open_position(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    _, session_id = _write_run_and_session(bank)
    _open_position(bank, session_id, ticker="SPY")

    decision = SessionDecision(
        session_id=session_id,
        decisions=[
            AssetDecision(
                ticker="SPY",
                action="BUY",
                strategy="MEAN_REVERSION",
                lot_size=5,
                exit_target={"type": "price_level", "value": 470.0},
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
    agent = ExecutionAgent(bank)

    with patch("alphoryn.execution.agent.TradingClient") as mock_tc_cls:
        agent.execute(decision)
        mock_tc_cls.assert_not_called()  # SPY BUY was blocked


def test_buy_on_different_ticker_not_blocked(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    _, session_id = _write_run_and_session(bank)
    _open_position(bank, session_id, ticker="SPY")  # SPY blocked

    decision = SessionDecision(
        session_id=session_id,
        decisions=[
            AssetDecision(
                ticker="SPY",
                action="HOLD",
                strategy="MEAN_REVERSION",
                lot_size=None,
                exit_target=None,
                reasoning="Position blocked.",
            ),
            AssetDecision(
                ticker="QQQ",
                action="BUY",
                strategy="MOMENTUM",
                lot_size=3,
                exit_target={"type": "trailing_stop", "trail_pct": 0.015},
                reasoning="ADX strong.",
            ),
        ],
    )
    agent = ExecutionAgent(bank)

    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"QQQ": MagicMock(ask_price=400.0)}

    with patch("alphoryn.execution.agent.TradingClient") as mock_tc_cls, \
         patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data):
        mock_tc = MagicMock()
        mock_tc_cls.return_value = mock_tc
        mock_account = MagicMock()
        mock_account.buying_power = "50000"
        mock_tc.get_account.return_value = mock_account
        agent.execute(decision)

    mock_tc.submit_order.assert_called_once()  # QQQ BUY executed


# ---------------------------------------------------------------------------
# Trailing stop watermark
# ---------------------------------------------------------------------------


def test_trailing_stop_watermark_updated_in_db(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    _, session_id = _write_run_and_session(bank)
    pos_id = _open_position(
        bank,
        session_id,
        stop_loss_price=430.0,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        trailing_stop_high_watermark=460.0,
    )

    monitor, _ = _make_monitor(bank, current_price=475.0)  # new high above 460

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    with DBSession(bank._engine) as s:
        pos = s.query(Position).filter(Position.id == pos_id).one()
        assert pos.trailing_stop_high_watermark == 475.0
        assert pos.status == "OPEN"  # not yet triggered (475 * 0.985 = 468.1 < 475)


def test_trailing_stop_hit_closes_position_in_db(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    _, session_id = _write_run_and_session(bank)
    pos_id = _open_position(
        bank,
        session_id,
        stop_loss_price=430.0,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        trailing_stop_high_watermark=500.0,
    )

    # stop_price = 500 * (1 - 0.015) = 492.5; current 490 < 492.5
    monitor, _ = _make_monitor(bank, current_price=490.0)

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    with DBSession(bank._engine) as s:
        pos = s.query(Position).filter(Position.id == pos_id).one()
        assert pos.status == "CLOSED_PROFIT_TARGET"
        assert pos.exit_reason == "PROFIT_TARGET"


# ---------------------------------------------------------------------------
# Window expiry
# ---------------------------------------------------------------------------


def test_window_expiry_closes_position_in_db(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    _, session_id = _write_run_and_session(bank)
    pos_id = _open_position(
        bank,
        session_id,
        stop_loss_price=430.0,
        exit_target={"type": "price_level", "value": 490.0},
        evaluation_window_session=5,
    )

    # current = 5 (matches evaluation_window_session); price between stop and target
    monitor, _ = _make_monitor(bank, current_price=455.0, current_session_ordinal=5)

    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_positions()

    with DBSession(bank._engine) as s:
        pos = s.query(Position).filter(Position.id == pos_id).one()
        assert pos.status == "CLOSED_WINDOW_EXPIRY"
        assert pos.exit_reason == "WINDOW_EXPIRY"
