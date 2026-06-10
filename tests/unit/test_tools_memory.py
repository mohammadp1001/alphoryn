"""Unit tests for tools.memory.tools — 6 tool functions."""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Initialise a fresh in-memory-backed SQLite DB for each test."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("config.DB_PATH", db_file)
    from db.schema import init_db
    init_db(db_file)
    return db_file


def _connect_to(db_file: Path):
    @contextmanager
    def _ctx(path=None):
        conn = sqlite3.connect(str(path or db_file), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return _ctx


# ── write_trade ───────────────────────────────────────────────────────────────

def test_write_trade_returns_trade_id_and_written(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))

    # Insert a session first to satisfy FK
    from db.schema import upsert_session
    upsert_session("sess-1", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import write_trade
    result = asyncio.run(write_trade(
        session_id="sess-1",
        cycle_index=0,
        symbol="XLK",
        strategy="MOMENTUM",
        side="buy",
        qty=10.0,
        entry_price=185.0,
        order_id="order-abc",
        optimist_level="LOW",
        pessimist_level="MEDIUM",
        final_risk_level="MEDIUM",
        risk_score=0.9,
        opt_win_rate=0.6,
        pess_win_rate=0.4,
        market_regime="BULL_TREND",
    ))

    assert result["written"] is True
    assert isinstance(result["trade_id"], str)
    assert len(result["trade_id"]) > 0


def test_write_trade_persists_to_db(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-2", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import write_trade
    result = asyncio.run(write_trade(
        session_id="sess-2",
        cycle_index=1,
        symbol="SPY",
        strategy="MOMENTUM",
        side="sell",
        qty=5.0,
        entry_price=450.0,
        order_id="order-xyz",
        optimist_level="LOW",
        pessimist_level="HIGH",
        final_risk_level="HIGH",
        risk_score=1.5,
        opt_win_rate=0.5,
        pess_win_rate=0.5,
        market_regime="BEAR_TREND",
    ))

    trade_id = result["trade_id"]
    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM trade_records WHERE id = ?", (trade_id,)).fetchone()
    conn.close()

    assert row is not None
    assert row["symbol"] == "SPY"
    assert row["side"] == "sell"


# ── resolve_trade ─────────────────────────────────────────────────────────────

def test_resolve_trade_returns_debate_winner(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-3", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import write_trade
    result = asyncio.run(write_trade(
        session_id="sess-3", cycle_index=0, symbol="QQQ", strategy="MOMENTUM",
        side="buy", qty=3.0, entry_price=400.0, order_id="ord-1",
        optimist_level="LOW", pessimist_level="LOW", final_risk_level="LOW",
        risk_score=0.5, opt_win_rate=0.6, pess_win_rate=0.4,
        market_regime="BULL_TREND",
    ))
    trade_id = result["trade_id"]

    from tools.memory.tools import resolve_trade
    resolve_result = asyncio.run(resolve_trade(trade_id, actual_pnl_pct=2.5))

    assert resolve_result["trade_id"] == trade_id
    assert resolve_result["resolved"] is True
    assert resolve_result["debate_winner"] in ("optimist", "pessimist", "tie")


def test_resolve_trade_pessimist_wins_on_loss(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-4", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import write_trade
    result = asyncio.run(write_trade(
        session_id="sess-4", cycle_index=0, symbol="IWM", strategy="MOMENTUM",
        side="buy", qty=2.0, entry_price=200.0, order_id="ord-2",
        optimist_level="LOW", pessimist_level="HIGH", final_risk_level="HIGH",
        risk_score=1.5, opt_win_rate=0.5, pess_win_rate=0.5,
        market_regime="BEAR_TREND",
    ))

    from tools.memory.tools import resolve_trade
    resolve_result = asyncio.run(resolve_trade(result["trade_id"], actual_pnl_pct=-3.0))

    assert resolve_result["debate_winner"] == "pessimist"


# ── get_calibration ───────────────────────────────────────────────────────────

def test_get_calibration_no_data_returns_equal_weight(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))

    from tools.memory.tools import get_calibration
    result = asyncio.run(get_calibration("BULL_TREND", "MOMENTUM"))

    assert result["has_data"] is False
    assert result["opt_win_rate"] == 0.5
    assert result["pess_win_rate"] == 0.5
    assert result["trade_count"] == 0


def test_get_calibration_returns_correct_keys(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))

    from tools.memory.tools import get_calibration
    result = asyncio.run(get_calibration("BEAR_TREND", "MEAN_REVERSION"))

    assert "has_data" in result
    assert "opt_win_rate" in result
    assert "pess_win_rate" in result
    assert "opt_summary" in result
    assert "pess_summary" in result
    assert "trade_count" in result


# ── get_session_cycles ────────────────────────────────────────────────────────

def test_get_session_cycles_returns_empty_for_unknown_session(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))

    from tools.memory.tools import get_session_cycles
    result = asyncio.run(get_session_cycles("nonexistent-session"))

    assert result["session_id"] == "nonexistent-session"
    assert result["cycles"] == []


def test_get_session_cycles_returns_recorded_cycles(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-5", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import record_cycle
    asyncio.run(record_cycle(
        session_id="sess-5", cycle_index=0, outcome="COMMITTED",
        shortlisted_symbols=["XLK", "SPY"], risk_level="LOW",
        abort_reason="", abort_stage="", trade_id="t-1", realised_pnl_pct=1.5,
    ))

    from tools.memory.tools import get_session_cycles
    result = asyncio.run(get_session_cycles("sess-5"))

    assert len(result["cycles"]) == 1
    assert result["cycles"][0]["cycle_index"] == 0
    assert result["cycles"][0]["outcome"] == "COMMITTED"
    assert "XLK" in result["cycles"][0]["shortlisted_symbols"]


# ── get_unresolved_trades ─────────────────────────────────────────────────────

def test_get_unresolved_trades_empty_db(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))

    from tools.memory.tools import get_unresolved_trades
    result = asyncio.run(get_unresolved_trades())

    assert result["trades"] == []


def test_get_unresolved_trades_shows_pending_trade(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-6", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import write_trade
    asyncio.run(write_trade(
        session_id="sess-6", cycle_index=0, symbol="GLD", strategy="MOMENTUM",
        side="buy", qty=1.0, entry_price=180.0, order_id="ord-unresolved",
        optimist_level="LOW", pessimist_level="LOW", final_risk_level="LOW",
        risk_score=0.5, opt_win_rate=0.5, pess_win_rate=0.5,
        market_regime="HIGH_VOL",
    ))

    from tools.memory.tools import get_unresolved_trades
    result = asyncio.run(get_unresolved_trades())

    assert len(result["trades"]) == 1
    assert result["trades"][0]["symbol"] == "GLD"
    assert result["trades"][0]["order_id"] == "ord-unresolved"


def test_get_unresolved_trades_includes_entry_price(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-7", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import write_trade
    asyncio.run(write_trade(
        session_id="sess-7", cycle_index=0, symbol="TLT", strategy="MOMENTUM",
        side="sell", qty=2.0, entry_price=95.5, order_id="ord-tlt",
        optimist_level="MEDIUM", pessimist_level="HIGH", final_risk_level="HIGH",
        risk_score=1.4, opt_win_rate=0.4, pess_win_rate=0.6,
        market_regime="CRISIS",
    ))

    from tools.memory.tools import get_unresolved_trades
    result = asyncio.run(get_unresolved_trades())

    trade = result["trades"][0]
    assert trade["entry_price"] == 95.5
    assert trade["side"] == "sell"


# ── record_cycle ──────────────────────────────────────────────────────────────

def test_record_cycle_committed(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-8", "SECTOR_ROTATION", "FULL_AUTO")

    from tools.memory.tools import record_cycle
    result = asyncio.run(record_cycle(
        session_id="sess-8", cycle_index=0, outcome="COMMITTED",
        shortlisted_symbols=["XLE", "XLF"], risk_level="MEDIUM",
        abort_reason="", abort_stage="", trade_id="t-abc", realised_pnl_pct=0.8,
    ))

    assert result["session_id"] == "sess-8"
    assert result["cycle_index"] == 0
    assert result["written"] is True


def test_record_cycle_aborted(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-9", "MEAN_REVERSION", "SEMI_AUTO")

    from tools.memory.tools import record_cycle
    result = asyncio.run(record_cycle(
        session_id="sess-9", cycle_index=2, outcome="ABORTED",
        shortlisted_symbols=[], risk_level="HIGH",
        abort_reason="risk_HIGH", abort_stage="risk_gate",
        trade_id="", realised_pnl_pct=0.0,
    ))

    assert result["written"] is True
    assert result["cycle_index"] == 2


def test_record_cycle_empty_symbols(tmp_db, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    from db.schema import upsert_session
    upsert_session("sess-10", "MOMENTUM", "SEMI_AUTO")

    from tools.memory.tools import get_session_cycles, record_cycle
    asyncio.run(record_cycle(
        session_id="sess-10", cycle_index=0, outcome="ABORTED",
        shortlisted_symbols=[], risk_level="",
        abort_reason="no_signals", abort_stage="analysis",
        trade_id="", realised_pnl_pct=0.0,
    ))

    result = asyncio.run(get_session_cycles("sess-10"))
    assert result["cycles"][0]["shortlisted_symbols"] == []
