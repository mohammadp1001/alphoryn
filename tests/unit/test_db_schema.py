"""Unit tests for SQLite schema — write-ahead pattern, calibration, outcome resolution."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from models.enums import DebateWinner, MarketRegime, Strategy
from models.memory import TradeRecord


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch DB_PATH to use a temporary file."""
    db = tmp_path / "test.db"
    import config
    monkeypatch.setattr(config, "DB_PATH", db)
    import db.schema as schema
    monkeypatch.setattr(schema, "DB_PATH", db)
    from db.schema import init_db
    init_db(db)
    return db


def _insert_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, started_at, strategy, mode) VALUES (?, ?, ?, ?)",
        (session_id, datetime.utcnow().isoformat(), "MOMENTUM", "SEMI_AUTO"),
    )


def _make_record(**overrides: object) -> TradeRecord:
    defaults = dict(
        id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        cycle_index=0,
        order_id=str(uuid.uuid4()),
        symbol="XLK",
        strategy=Strategy.MOMENTUM,
        market_regime=MarketRegime.BULL_TREND,
        side="buy",
        qty=10.0,
        entry_price=200.0,
        optimist_verdict="LOW",
        pessimist_verdict="MEDIUM",
        risk_level="MEDIUM",
        risk_score=0.9,
        opt_win_rate_at_trade=0.5,
        pess_win_rate_at_trade=0.5,
        executed_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    return TradeRecord(**defaults)  # type: ignore[arg-type]


# ── Write-ahead ───────────────────────────────────────────────────────────────

def test_write_trade_record_persists(tmp_db: Path) -> None:
    from db.schema import _connect, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)

    with _connect(tmp_db) as conn:
        row = conn.execute("SELECT * FROM trade_records WHERE id = ?", (record.id,)).fetchone()

    assert row is not None
    assert row["symbol"] == "XLK"
    assert row["outcome_resolved"] == 0


def test_write_trade_record_is_idempotent_within_session(tmp_db: Path) -> None:
    from db.schema import _connect, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)

    with _connect(tmp_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM trade_records WHERE id = ?", (record.id,)
        ).fetchone()[0]

    assert count == 1


# ── Outcome resolution ────────────────────────────────────────────────────────

def test_resolve_outcome_profitable_trade_optimist_wins(tmp_db: Path) -> None:
    from db.schema import _connect, resolve_outcome, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)
    result = resolve_outcome(record.id, 1.5)  # pnl >= 0.5% → optimist wins

    assert result.updated is True
    assert result.debate_winner == DebateWinner.OPTIMIST

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT debate_winner, outcome_resolved FROM trade_records WHERE id = ?",
            (record.id,),
        ).fetchone()
    assert row["outcome_resolved"] == 1
    assert row["debate_winner"] == "optimist"


def test_resolve_outcome_losing_trade_pessimist_wins(tmp_db: Path) -> None:
    from db.schema import _connect, resolve_outcome, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)
    result = resolve_outcome(record.id, -2.0)  # pnl < 0 → pessimist wins

    assert result.debate_winner == DebateWinner.PESSIMIST


def test_resolve_outcome_tie_in_deadzone(tmp_db: Path) -> None:
    from db.schema import _connect, resolve_outcome, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)
    result = resolve_outcome(record.id, 0.3)  # 0 <= pnl < 0.5 → TIE

    assert result.debate_winner == DebateWinner.TIE


# ── Calibration ───────────────────────────────────────────────────────────────

def test_calibration_cold_start_has_no_data(tmp_db: Path) -> None:
    from db.schema import get_calibration

    cal = get_calibration("optimist", MarketRegime.BULL_TREND, Strategy.MOMENTUM)
    assert cal.has_data is False
    assert cal.win_rate == 0.5
    assert "Starting at equal weight" in cal.formatted_summary


def test_calibration_updates_after_outcome(tmp_db: Path) -> None:
    from db.schema import _connect, get_calibration, resolve_outcome, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)
    resolve_outcome(record.id, 1.0)  # optimist wins

    cal = get_calibration("optimist", MarketRegime.BULL_TREND, Strategy.MOMENTUM)
    assert cal.has_data is True
    assert cal.wins == 1
    assert cal.losses == 0


# ── Unresolved trades ─────────────────────────────────────────────────────────

def test_get_unresolved_trades_returns_unresolved(tmp_db: Path) -> None:
    from db.schema import _connect, get_unresolved_trades, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)

    unresolved = get_unresolved_trades()
    ids = [t.id for t in unresolved]
    assert record.id in ids


def test_get_unresolved_trades_excludes_resolved(tmp_db: Path) -> None:
    from db.schema import _connect, get_unresolved_trades, resolve_outcome, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)
    resolve_outcome(record.id, 0.8)

    unresolved = get_unresolved_trades()
    ids = [t.id for t in unresolved]
    assert record.id not in ids


def test_get_unresolved_trades_with_session_id_filter(tmp_db: Path) -> None:
    """With a session_id filter, only that session's unresolved trades are returned."""
    from db.schema import _connect, get_unresolved_trades, write_trade_record

    rec_a = _make_record(session_id="sess-fa", order_id="ord-fa")
    rec_b = _make_record(session_id="sess-fb", order_id="ord-fb")

    with _connect(tmp_db) as conn:
        _insert_session(conn, "sess-fa")
        _insert_session(conn, "sess-fb")

    write_trade_record(rec_a)
    write_trade_record(rec_b)

    result = get_unresolved_trades(session_id="sess-fa")
    ids = [t.id for t in result]
    assert rec_a.id in ids
    assert rec_b.id not in ids


# ── mark_outcome_timed_out ────────────────────────────────────────────────────

def test_mark_outcome_timed_out_sets_flag(tmp_db: Path) -> None:
    from db.schema import _connect, mark_outcome_timed_out, write_trade_record

    record = _make_record()
    with _connect(tmp_db) as conn:
        _insert_session(conn, record.session_id)
    write_trade_record(record)

    mark_outcome_timed_out(record.id)

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT outcome_timed_out FROM trade_records WHERE id = ?", (record.id,)
        ).fetchone()
    assert row["outcome_timed_out"] == 1


# ── get_cycle_history ─────────────────────────────────────────────────────────

def test_get_cycle_history_empty(tmp_db: Path) -> None:
    from db.schema import _connect, get_cycle_history

    with _connect(tmp_db) as conn:
        _insert_session(conn, "sess-ch-empty")

    result = get_cycle_history("sess-ch-empty")
    assert result == []


def test_get_cycle_history_with_resolved_trade(tmp_db: Path) -> None:
    from db.schema import _connect, get_cycle_history, resolve_outcome, write_trade_record

    session_id = "sess-ch-trade"
    record = _make_record(session_id=session_id)
    with _connect(tmp_db) as conn:
        _insert_session(conn, session_id)
    write_trade_record(record)
    resolve_outcome(record.id, 2.0)

    result = get_cycle_history(session_id)
    assert len(result) == 1
    assert result[0].trade_id == record.id


# ── _update_regime_stats update branch ───────────────────────────────────────

def test_update_regime_stats_update_branch_triggered(tmp_db: Path) -> None:
    """Resolving two trades with same regime exercises the UPDATE branch."""
    from db.schema import _connect, resolve_outcome, write_trade_record

    session_id = "sess-regime-upd"
    with _connect(tmp_db) as conn:
        _insert_session(conn, session_id)

    r1 = _make_record(session_id=session_id, order_id="ord-rup-1")
    r2 = _make_record(session_id=session_id, order_id="ord-rup-2")
    write_trade_record(r1)
    write_trade_record(r2)

    resolve_outcome(r1.id, 1.5)   # INSERT branch — creates row
    resolve_outcome(r2.id, -0.5)  # UPDATE branch — updates row

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT total_trades FROM regime_stats WHERE market_regime = 'BULL_TREND'"
        ).fetchone()
    assert row is not None
    assert row["total_trades"] == 2


# ── _connect rollback on exception ───────────────────────────────────────────

def test_connect_rollback_reraises_exception(tmp_db: Path) -> None:
    """_connect must rollback and re-raise the exception."""
    from db.schema import _connect

    with pytest.raises(RuntimeError, match="deliberate"), _connect(tmp_db) as conn:
        # Any valid SQL statement first, then raise
        conn.execute("SELECT 1")
        raise RuntimeError("deliberate")
