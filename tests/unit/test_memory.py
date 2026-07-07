"""Unit tests for alphoryn/memory/ (schema.py + bank.py).

Uses an in-memory SQLite database (:memory:) so no filesystem access is
needed and every test starts from a clean state.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session as DBSession

from alphoryn.memory.bank import MemoryBank, MemoryBankError
from alphoryn.memory.schema import (
    FeedbackEvaluation,
    MemoryEntry,
    Position,
    Run,
    Session,
    create_tables,
    get_engine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _in_memory_bank() -> MemoryBank:
    """Return a MemoryBank backed by an in-memory SQLite database."""
    bank = MemoryBank.__new__(MemoryBank)
    bank._engine = create_engine("sqlite:///:memory:", echo=False)
    create_tables(bank._engine)
    return bank


def _sample_run(session_count_planned: int = 24) -> Run:
    return Run(
        started_at=_NOW,
        config_snapshot='{"tickers":["SPY","QQQ"]}',
        session_count_planned=session_count_planned,
    )


def _sample_session(run_id: int, ordinal: int = 1) -> Session:
    return Session(
        id=f"run-{run_id}/session-{ordinal:04d}",
        run_id=run_id,
        candle_close_at=_NOW,
        created_at=_NOW,
        status="COMPLETED",
    )


def _sample_position(session_id: str, status: str = "OPEN", ticker: str = "SPY") -> Position:
    return Position(
        session_id=session_id,
        ticker=ticker,
        strategy="MOMENTUM",
        direction="BUY",
        entry_price=450.00,
        entry_time=_NOW,
        lot_size=10.0,
        stop_loss_price=441.00,
        exit_target='{"type": "fixed", "target_price": 460.00}',
        evaluation_window_session=5,
        status=status,
    )


# ---------------------------------------------------------------------------
# get_engine
# ---------------------------------------------------------------------------


def test_get_engine_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "memory.db"
    engine = get_engine(str(nested))
    assert nested.parent.exists()
    engine.dispose()


def test_get_engine_expands_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[attr-defined]
    engine = get_engine("~/test.db")
    assert engine is not None
    engine.dispose()


# ---------------------------------------------------------------------------
# create_tables / schema integrity
# ---------------------------------------------------------------------------


def test_create_tables_creates_all_five_entities() -> None:
    engine = create_engine("sqlite:///:memory:")
    create_tables(engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert tables == {"runs", "sessions", "positions", "feedback_evaluations", "memory_entries"}


def test_run_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    create_tables(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("runs")}
    assert {"id", "started_at", "ended_at", "config_snapshot", "session_count_planned"} <= cols


def test_position_status_values_accepted() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        run = s.query(Run).filter(Run.id == run_id).one()
        sess = _sample_session(run.id)
        s.add(sess)
        s.commit()
        for status in (
            "OPEN",
            "CLOSED_STOP_LOSS",
            "CLOSED_PROFIT_TARGET",
            "CLOSED_WINDOW_EXPIRY",
            "EVALUATED",
            "EVALUATION_FAILED",
        ):
            pos = _sample_position(sess.id, status=status)
            s.add(pos)
        s.commit()
        count = s.query(Position).count()
    assert count == 6


# ---------------------------------------------------------------------------
# MemoryBank.__init__ — error handling
# ---------------------------------------------------------------------------


def test_memory_bank_init_inaccessible_path_raises(tmp_path: Path) -> None:
    # Point to a directory that cannot be written to by patching get_engine
    with patch("alphoryn.memory.bank.get_engine", side_effect=OSError("permission denied")):
        with pytest.raises(MemoryBankError, match="Memory bank inaccessible"):
            MemoryBank(str(tmp_path / "bad.db"))


def test_memory_bank_init_corrupt_db_raises(tmp_path: Path) -> None:
    bad_db = tmp_path / "corrupt.db"
    bad_db.write_bytes(b"NOT A SQLITE FILE\x00\xff")
    with pytest.raises(MemoryBankError, match="Memory bank inaccessible"):
        MemoryBank(str(bad_db))


def test_memory_bank_init_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    bank = MemoryBank(str(db_path))
    tables = set(inspect(bank._engine).get_table_names())
    assert "runs" in tables
    assert "positions" in tables


# ---------------------------------------------------------------------------
# load_open_positions — startup query
# ---------------------------------------------------------------------------


def test_load_open_positions_empty_db() -> None:
    bank = _in_memory_bank()
    assert bank.load_open_positions() == []


def test_load_open_positions_returns_only_open() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
        s.add(_sample_position(sess.id, status="OPEN"))
        s.add(_sample_position(sess.id, status="CLOSED_STOP_LOSS"))
        s.add(_sample_position(sess.id, status="EVALUATED"))
        s.commit()

    open_positions = bank.load_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0].status == "OPEN"


def test_load_open_positions_across_multiple_runs() -> None:
    bank = _in_memory_bank()
    for _ in range(3):
        run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
        with DBSession(bank._engine) as s:
            sess = _sample_session(run_id)
            s.add(sess)
            s.commit()
            s.add(_sample_position(sess.id, status="OPEN"))
            s.commit()

    open_positions = bank.load_open_positions()
    assert len(open_positions) == 3


def test_load_open_positions_ordered_by_entry_time() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)

    # SQLite strips tzinfo on round-trip — use naive datetimes for comparison
    t1 = datetime(2024, 1, 1)
    t2 = datetime(2024, 1, 2)
    t3 = datetime(2024, 1, 3)

    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
        for t in (t3, t1, t2):
            pos = _sample_position(sess.id, status="OPEN")
            pos.entry_time = t
            s.add(pos)
        s.commit()

    positions = bank.load_open_positions()
    assert [p.entry_time for p in positions] == [t1, t2, t3]


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


def test_start_run_returns_id() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    assert isinstance(run_id, int)
    assert run_id > 0


def test_end_run_sets_ended_at() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    bank.end_run(run_id)
    with DBSession(bank._engine) as s:
        run = s.query(Run).filter(Run.id == run_id).one()
        assert run.ended_at is not None


# ---------------------------------------------------------------------------
# Session writes
# ---------------------------------------------------------------------------


def test_write_session_persists() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    sess = _sample_session(run_id)
    bank.write_session(sess)
    with DBSession(bank._engine) as s:
        result = s.query(Session).filter(Session.id == sess.id).one()
        assert result.status == "COMPLETED"


def test_write_session_idempotent() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    sess = _sample_session(run_id)
    bank.write_session(sess)
    sess.status = "SKIPPED_TIMEOUT"
    bank.write_session(sess)
    with DBSession(bank._engine) as s:
        result = s.query(Session).filter(Session.id == sess.id).one()
        assert result.status == "SKIPPED_TIMEOUT"


# ---------------------------------------------------------------------------
# Position writes
# ---------------------------------------------------------------------------


def test_write_position_returns_id() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    pos = _sample_position(f"run-{run_id}/session-0001")
    pos_id = bank.write_position(pos)
    assert isinstance(pos_id, int)
    assert pos_id > 0


def test_update_position_close_sets_exit_fields() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    pos = _sample_position(f"run-{run_id}/session-0001")
    pos_id = bank.write_position(pos)

    bank.update_position_close(
        pos_id,
        exit_price=460.0,
        exit_time=_NOW,
        exit_reason="PROFIT_TARGET",
        status="CLOSED_PROFIT_TARGET",
    )
    with DBSession(bank._engine) as s:
        result = s.query(Position).filter(Position.id == pos_id).one()
        assert result.exit_price == pytest.approx(460.0)
        assert result.status == "CLOSED_PROFIT_TARGET"
        assert result.exit_reason == "PROFIT_TARGET"


def test_update_position_close_with_watermark() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    pos = _sample_position(f"run-{run_id}/session-0001")
    pos_id = bank.write_position(pos)
    bank.update_position_close(
        pos_id,
        exit_price=470.0,
        exit_time=_NOW,
        exit_reason="STOP_LOSS",
        status="CLOSED_STOP_LOSS",
        trailing_stop_high_watermark=465.0,
    )
    with DBSession(bank._engine) as s:
        result = s.query(Position).filter(Position.id == pos_id).one()
        assert result.trailing_stop_high_watermark == pytest.approx(465.0)


def test_update_trailing_watermark() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    pos = _sample_position(f"run-{run_id}/session-0001")
    pos_id = bank.write_position(pos)
    bank.update_trailing_watermark(pos_id, 455.0)
    with DBSession(bank._engine) as s:
        result = s.query(Position).filter(Position.id == pos_id).one()
        assert result.trailing_stop_high_watermark == pytest.approx(455.0)


# ---------------------------------------------------------------------------
# Feedback evaluation writes
# ---------------------------------------------------------------------------


def test_write_feedback_evaluation_persists_and_updates_position() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    pos = _sample_position(f"run-{run_id}/session-0001", status="CLOSED_PROFIT_TARGET")
    pos_id = bank.write_position(pos)

    evaluation = FeedbackEvaluation(
        position_id=pos_id,
        evaluated_at=_NOW,
        candle_close_price=462.0,
        thesis_summary="Momentum confirmed",
        outcome_judgment="CORRECT",
        reasoning="Price hit target as predicted",
    )
    bank.write_feedback_evaluation(evaluation, "EVALUATED")

    with DBSession(bank._engine) as s:
        result_pos = s.query(Position).filter(Position.id == pos_id).one()
        assert result_pos.status == "EVALUATED"
        result_eval = s.query(FeedbackEvaluation).filter(
            FeedbackEvaluation.position_id == pos_id
        ).one()
        assert result_eval.outcome_judgment == "CORRECT"


# ---------------------------------------------------------------------------
# Memory entry writes
# ---------------------------------------------------------------------------


def test_write_memory_entry_persists() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()

    entry = MemoryEntry(
        ticker="SPY",
        strategy="MOMENTUM",
        session_id=f"run-{run_id}/session-0001",
        decision="BUY",
        regime_context='{"trend":"up"}',
        created_at=_NOW,
    )
    bank.write_memory_entry(entry)

    with DBSession(bank._engine) as s:
        result = s.query(MemoryEntry).filter(MemoryEntry.ticker == "SPY").one()
        assert result.decision == "BUY"


def test_update_memory_entry_judgment() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    session_id = f"run-{run_id}/session-0001"
    entry = MemoryEntry(
        ticker="QQQ",
        strategy="MEAN_REVERSION",
        session_id=session_id,
        decision="HOLD",
        regime_context="{}",
        created_at=_NOW,
    )
    bank.write_memory_entry(entry)
    bank.update_memory_entry_judgment(session_id, "QQQ", "MEAN_REVERSION", "INCORRECT")
    with DBSession(bank._engine) as s:
        result = s.query(MemoryEntry).filter(MemoryEntry.ticker == "QQQ").one()
        assert result.outcome_judgment == "INCORRECT"


# ---------------------------------------------------------------------------
# Queries for scheduler / feedback trigger
# ---------------------------------------------------------------------------


def test_get_positions_due_for_feedback_returns_closed_at_window() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()

    pos1 = _sample_position(f"run-{run_id}/session-0001", status="CLOSED_PROFIT_TARGET")
    pos1.evaluation_window_session = 5
    pos2 = _sample_position(f"run-{run_id}/session-0001", status="CLOSED_STOP_LOSS")
    pos2.evaluation_window_session = 10  # different window
    pos3 = _sample_position(f"run-{run_id}/session-0001", status="OPEN")
    pos3.evaluation_window_session = 5  # OPEN, should not appear

    bank.write_position(pos1)
    bank.write_position(pos2)
    bank.write_position(pos3)

    due = bank.get_positions_due_for_feedback(current_session_ordinal=5)
    assert len(due) == 1
    assert due[0].status == "CLOSED_PROFIT_TARGET"


def test_get_positions_due_for_feedback_excludes_already_evaluated() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()

    pos = _sample_position(f"run-{run_id}/session-0001", status="CLOSED_PROFIT_TARGET")
    pos.evaluation_window_session = 5
    pos_id = bank.write_position(pos)

    evaluation = FeedbackEvaluation(
        position_id=pos_id,
        evaluated_at=_NOW,
        candle_close_price=460.0,
        thesis_summary="ok",
        outcome_judgment="CORRECT",
        reasoning="good",
    )
    bank.write_feedback_evaluation(evaluation, "EVALUATED")

    # Now status is EVALUATED but evaluation_window_session was 5
    # The EVALUATED status is not in the closed_statuses filter → no results
    due = bank.get_positions_due_for_feedback(current_session_ordinal=5)
    assert due == []


def test_get_recent_memory_entries_returns_latest_first() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    session_id = f"run-{run_id}/session-0001"

    for i in range(3):
        entry = MemoryEntry(
            ticker="SPY",
            strategy="MOMENTUM",
            session_id=session_id,
            decision="BUY",
            regime_context="{}",
            created_at=datetime(2024, 1, i + 1, tzinfo=UTC),
        )
        bank.write_memory_entry(entry)

    entries = bank.get_recent_memory_entries("SPY", limit=2)
    assert len(entries) == 2
    # Most recent first
    assert entries[0].created_at > entries[1].created_at


def test_get_recent_memory_entries_filters_by_ticker() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    session_id = f"run-{run_id}/session-0001"

    for ticker in ("SPY", "QQQ", "SPY"):
        entry = MemoryEntry(
            ticker=ticker,
            strategy="MOMENTUM",
            session_id=session_id,
            decision="BUY",
            regime_context="{}",
            created_at=_NOW,
        )
        bank.write_memory_entry(entry)

    spy_entries = bank.get_recent_memory_entries("SPY")
    assert all(e.ticker == "SPY" for e in spy_entries)
    assert len(spy_entries) == 2


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


def test_get_session_returns_session_when_found() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    sess = _sample_session(run_id)
    bank.write_session(sess)
    result = bank.get_session(sess.id)
    assert result is not None
    assert result.id == sess.id


def test_get_session_returns_none_when_not_found() -> None:
    bank = _in_memory_bank()
    result = bank.get_session("run-999/session-0001")
    assert result is None


def test_feedback_evaluation_attempt_count_default_is_one() -> None:
    bank = _in_memory_bank()
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 24)
    with DBSession(bank._engine) as s:
        sess = _sample_session(run_id)
        s.add(sess)
        s.commit()
    pos = _sample_position(f"run-{run_id}/session-0001", status="CLOSED_STOP_LOSS")
    pos_id = bank.write_position(pos)

    evaluation = FeedbackEvaluation(
        position_id=pos_id,
        evaluated_at=_NOW,
        candle_close_price=440.0,
        thesis_summary="Stop hit",
        outcome_judgment="INCORRECT",
        reasoning="Market reversed",
    )
    bank.write_feedback_evaluation(evaluation, "EVALUATED")

    with DBSession(bank._engine) as s:
        result = s.query(FeedbackEvaluation).filter(
            FeedbackEvaluation.position_id == pos_id
        ).one()
        assert result.attempt_count == 1
