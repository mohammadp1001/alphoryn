"""Unit tests for tools.coordinator.tools — 8 coordinator tools."""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "coord_test.db"
    monkeypatch.setattr("config.DB_PATH", db_file)

    def _connect(path=None):
        @contextmanager
        def _ctx():
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
        return _ctx()

    monkeypatch.setattr("db.schema._connect", _connect)

    from db.schema import init_db
    init_db(db_file)
    return db_file


# ── check_loss_limit ──────────────────────────────────────────────────────────

def test_check_loss_limit_not_breached():
    from tools.coordinator.tools import check_loss_limit
    result = asyncio.run(check_loss_limit(
        session_realised_pnl_eur=-100.0,
        loss_limit_eur=500.0,
        unrealised_pnl_eur=-50.0,
    ))

    assert result["breached"] is False
    assert result["warning"] is False
    assert abs(result["consumed_pct"] - 20.0) < 0.01
    assert abs(result["remaining_eur"] - 400.0) < 0.01


def test_check_loss_limit_warning_threshold():
    from tools.coordinator.tools import check_loss_limit
    result = asyncio.run(check_loss_limit(
        session_realised_pnl_eur=-400.0,
        loss_limit_eur=500.0,
        unrealised_pnl_eur=0.0,
    ))

    assert result["breached"] is False
    assert result["warning"] is True
    assert abs(result["consumed_pct"] - 80.0) < 0.01


def test_check_loss_limit_breached():
    from tools.coordinator.tools import check_loss_limit
    result = asyncio.run(check_loss_limit(
        session_realised_pnl_eur=-500.0,
        loss_limit_eur=500.0,
        unrealised_pnl_eur=0.0,
    ))

    assert result["breached"] is True
    assert result["consumed_pct"] >= 100.0
    assert result["remaining_eur"] <= 0.0


def test_check_loss_limit_zero_loss_limit():
    from tools.coordinator.tools import check_loss_limit
    result = asyncio.run(check_loss_limit(
        session_realised_pnl_eur=0.0,
        loss_limit_eur=0.0,
        unrealised_pnl_eur=0.0,
    ))
    assert result["consumed_pct"] == 0.0


def test_check_loss_limit_positive_pnl_no_breach():
    from tools.coordinator.tools import check_loss_limit
    result = asyncio.run(check_loss_limit(
        session_realised_pnl_eur=200.0,  # profit
        loss_limit_eur=500.0,
        unrealised_pnl_eur=100.0,
    ))
    assert result["breached"] is False
    assert result["consumed_pct"] <= 0.0


def test_check_loss_limit_includes_unrealised_in_output():
    from tools.coordinator.tools import check_loss_limit
    result = asyncio.run(check_loss_limit(-100.0, 500.0, -75.0))
    assert result["unrealised_pnl_eur"] == -75.0


# ── select_shortlist ──────────────────────────────────────────────────────────

def test_select_shortlist_picks_top_n():
    signals = [
        {"symbol": "XLK", "combined_score": 0.9},
        {"symbol": "SPY", "combined_score": 0.7},
        {"symbol": "QQQ", "combined_score": 0.5},
    ]
    from tools.coordinator.tools import select_shortlist
    result = asyncio.run(select_shortlist(signals, shortlist_n=2, strategy="MOMENTUM"))

    assert result["n"] == 2
    assert result["strategy"] == "MOMENTUM"
    assert result["shortlisted"][0]["symbol"] == "XLK"
    assert result["shortlisted"][1]["symbol"] == "SPY"


def test_select_shortlist_caps_at_max_shortlist_n():
    signals = [{"symbol": f"ETF{i}", "combined_score": float(i)} for i in range(10)]
    from tools.coordinator.tools import select_shortlist
    from config import MAX_SHORTLIST_N
    result = asyncio.run(select_shortlist(signals, shortlist_n=99, strategy="MOMENTUM"))

    assert result["n"] <= MAX_SHORTLIST_N


def test_select_shortlist_empty_signals():
    from tools.coordinator.tools import select_shortlist
    result = asyncio.run(select_shortlist([], shortlist_n=2, strategy="SECTOR_ROTATION"))
    assert result["n"] == 0
    assert result["shortlisted"] == []


def test_select_shortlist_fewer_signals_than_n():
    signals = [{"symbol": "XLK", "combined_score": 0.8}]
    from tools.coordinator.tools import select_shortlist
    result = asyncio.run(select_shortlist(signals, shortlist_n=3, strategy="MEAN_REVERSION"))
    assert result["n"] == 1


# ── synthesise_risk ───────────────────────────────────────────────────────────

def test_synthesise_risk_equal_weights_medium():
    from tools.coordinator.tools import synthesise_risk
    result = asyncio.run(synthesise_risk("LOW", "low text", "HIGH", "high text", 0.5, 0.5))
    assert result["risk_level"] == "MEDIUM"
    assert "risk_score" in result
    assert "debate_winner" in result
    assert "synthesis_reasoning" in result


def test_synthesise_risk_both_low_gives_low():
    from tools.coordinator.tools import synthesise_risk
    result = asyncio.run(synthesise_risk("LOW", "", "LOW", "", 0.5, 0.5))
    assert result["risk_level"] == "LOW"


def test_synthesise_risk_both_high_gives_high():
    from tools.coordinator.tools import synthesise_risk
    result = asyncio.run(synthesise_risk("HIGH", "", "HIGH", "", 0.5, 0.5))
    assert result["risk_level"] == "HIGH"


def test_synthesise_risk_zero_weights_fallback():
    from tools.coordinator.tools import synthesise_risk
    result = asyncio.run(synthesise_risk("LOW", "", "HIGH", "", 0.0, 0.0))
    assert result["risk_score"] == 1.0  # fallback = MEDIUM score


def test_synthesise_risk_pessimist_override():
    from tools.coordinator.tools import synthesise_risk
    # pessimist HIGH + high win rate → override to HIGH
    result = asyncio.run(synthesise_risk("LOW", "", "HIGH", "", 0.8, 0.7))
    assert result["risk_level"] == "HIGH"


# ── update_plan_state ─────────────────────────────────────────────────────────

def test_update_plan_state_returns_correct_response():
    from tools.coordinator.tools import update_plan_state
    result = asyncio.run(update_plan_state("sess-1", "market_regime", "BULL_TREND"))

    assert result["session_id"] == "sess-1"
    assert result["field"] == "market_regime"
    assert result["value"] == "BULL_TREND"
    assert result["updated"] is True


# ── abort_cycle ───────────────────────────────────────────────────────────────

def test_abort_cycle_returns_aborted_outcome():
    from tools.coordinator.tools import abort_cycle
    result = asyncio.run(abort_cycle("sess-1", 2, "risk too high", "risk_gate"))

    assert result["outcome"] == "ABORTED"
    assert result["reason"] == "risk too high"
    assert result["stage"] == "risk_gate"
    assert result["session_id"] == "sess-1"
    assert result["cycle_index"] == 2


# ── get_session_summary ───────────────────────────────────────────────────────

def test_get_session_summary_empty_session(tmp_db):
    from tools.coordinator.tools import get_session_summary
    result = asyncio.run(get_session_summary("unknown-session"))

    assert result["session_id"] == "unknown-session"
    assert result["cycle_count"] == 0
    assert result["committed_count"] == 0
    assert result["aborted_count"] == 0


def test_get_session_summary_with_cycles(tmp_db):
    from db.schema import upsert_session

    upsert_session("sess-sum", "MOMENTUM", "SEMI_AUTO")

    # Insert cycle records directly
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO cycle_records (session_id, cycle_index, outcome, realised_pnl_pct)
        VALUES ('sess-sum', 0, 'COMMITTED', 1.5)
    """)
    conn.execute("""
        INSERT INTO cycle_records (session_id, cycle_index, outcome, realised_pnl_pct)
        VALUES ('sess-sum', 1, 'ABORTED', 0.0)
    """)
    conn.commit()
    conn.close()

    from tools.coordinator.tools import get_session_summary
    result = asyncio.run(get_session_summary("sess-sum"))

    assert result["cycle_count"] == 2
    assert result["committed_count"] == 1
    assert result["aborted_count"] == 1
    assert abs(result["session_realised_pnl_eur"] - 1.5) < 0.01


# ── resolve_unresolved_trades ─────────────────────────────────────────────────

def test_resolve_unresolved_trades_empty_db(tmp_db):
    from tools.coordinator.tools import resolve_unresolved_trades
    result = asyncio.run(resolve_unresolved_trades())

    assert result["resolved_count"] == 0
    assert result["failed_count"] == 0
    assert result["details"] == []


def test_resolve_unresolved_trades_with_pending_buy_trade(tmp_db, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from db.schema import upsert_session, write_trade_record
    from models.memory import TradeRecord
    from models.enums import Strategy, MarketRegime
    from datetime import datetime

    upsert_session("sess-res-buy", "MOMENTUM", "SEMI_AUTO")

    trade = TradeRecord(
        id="trade-open-buy",
        session_id="sess-res-buy",
        cycle_index=0,
        order_id="alpaca-order-buy",
        symbol="XLK",
        strategy=Strategy.MOMENTUM,
        market_regime=MarketRegime.BULL_TREND,
        side="buy",
        qty=5.0,
        entry_price=180.0,
        optimist_verdict="LOW",
        pessimist_verdict="MEDIUM",
        risk_level="MEDIUM",
        risk_score=0.9,
        opt_win_rate_at_trade=0.5,
        pess_win_rate_at_trade=0.5,
        executed_at=datetime.utcnow(),
    )
    write_trade_record(trade)

    mock_order = MagicMock()
    mock_order.filled_avg_price = "185.0"

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.get_order_by_id.return_value = mock_order

    with patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()):
        with patch("alpaca.trading.client.TradingClient", mock_client_cls):
            from tools.coordinator.tools import resolve_unresolved_trades
            result = asyncio.run(resolve_unresolved_trades())

    assert result["resolved_count"] == 1
    assert result["failed_count"] == 0


def test_resolve_unresolved_trades_with_pending_sell_trade(tmp_db, monkeypatch):
    """sell-side trade: pnl is negated (line 228 coverage)."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from db.schema import upsert_session, write_trade_record
    from models.memory import TradeRecord
    from models.enums import Strategy, MarketRegime
    from datetime import datetime

    upsert_session("sess-res-sell", "MOMENTUM", "SEMI_AUTO")

    trade = TradeRecord(
        id="trade-open-sell",
        session_id="sess-res-sell",
        cycle_index=0,
        order_id="alpaca-order-sell",
        symbol="SPY",
        strategy=Strategy.MOMENTUM,
        market_regime=MarketRegime.BULL_TREND,
        side="sell",  # ← triggers line 228
        qty=3.0,
        entry_price=190.0,
        optimist_verdict="LOW",
        pessimist_verdict="MEDIUM",
        risk_level="MEDIUM",
        risk_score=0.8,
        opt_win_rate_at_trade=0.5,
        pess_win_rate_at_trade=0.5,
        executed_at=datetime.utcnow(),
    )
    write_trade_record(trade)

    mock_order = MagicMock()
    mock_order.filled_avg_price = "188.0"  # price below entry → sell profit

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.get_order_by_id.return_value = mock_order

    with patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()):
        with patch("alpaca.trading.client.TradingClient", mock_client_cls):
            from tools.coordinator.tools import resolve_unresolved_trades
            result = asyncio.run(resolve_unresolved_trades())

    assert result["resolved_count"] == 1


def test_resolve_unresolved_trades_no_fill_price(tmp_db, monkeypatch):
    """Trade with filled_avg_price=0 → unresolvable path (lines 234-236)."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from db.schema import upsert_session, write_trade_record
    from models.memory import TradeRecord
    from models.enums import Strategy, MarketRegime
    from datetime import datetime

    upsert_session("sess-res-nofill", "MOMENTUM", "SEMI_AUTO")

    trade = TradeRecord(
        id="trade-open-nofill",
        session_id="sess-res-nofill",
        cycle_index=0,
        order_id="alpaca-order-nofill",
        symbol="QQQ",
        strategy=Strategy.MOMENTUM,
        market_regime=MarketRegime.BULL_TREND,
        side="buy",
        qty=2.0,
        entry_price=300.0,
        optimist_verdict="LOW",
        pessimist_verdict="MEDIUM",
        risk_level="MEDIUM",
        risk_score=0.7,
        opt_win_rate_at_trade=0.5,
        pess_win_rate_at_trade=0.5,
        executed_at=datetime.utcnow(),
    )
    write_trade_record(trade)

    mock_order = MagicMock()
    mock_order.filled_avg_price = "0"  # zero fill → no resolution

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.get_order_by_id.return_value = mock_order

    with patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()):
        with patch("alpaca.trading.client.TradingClient", mock_client_cls):
            from tools.coordinator.tools import resolve_unresolved_trades
            result = asyncio.run(resolve_unresolved_trades())

    assert result["failed_count"] == 1
    assert result["details"][0]["status"] == "unresolvable"


def test_resolve_unresolved_trades_api_exception(tmp_db, monkeypatch):
    """API exception → error path (lines 237-239)."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from db.schema import upsert_session, write_trade_record
    from models.memory import TradeRecord
    from models.enums import Strategy, MarketRegime
    from datetime import datetime

    upsert_session("sess-res-exc", "MOMENTUM", "SEMI_AUTO")

    trade = TradeRecord(
        id="trade-open-exc",
        session_id="sess-res-exc",
        cycle_index=0,
        order_id="alpaca-order-exc",
        symbol="IWM",
        strategy=Strategy.MOMENTUM,
        market_regime=MarketRegime.BULL_TREND,
        side="buy",
        qty=1.0,
        entry_price=200.0,
        optimist_verdict="LOW",
        pessimist_verdict="LOW",
        risk_level="LOW",
        risk_score=0.5,
        opt_win_rate_at_trade=0.5,
        pess_win_rate_at_trade=0.5,
        executed_at=datetime.utcnow(),
    )
    write_trade_record(trade)

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.get_order_by_id.side_effect = Exception("API timeout")

    with patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()):
        with patch("alpaca.trading.client.TradingClient", mock_client_cls):
            from tools.coordinator.tools import resolve_unresolved_trades
            result = asyncio.run(resolve_unresolved_trades())

    assert result["failed_count"] == 1
    assert result["details"][0]["status"] == "error"


# ── request_hitl ──────────────────────────────────────────────────────────────

def test_request_hitl_confirm():
    from tools.coordinator.tools import request_hitl

    async def fake_wait_for(coro, timeout):
        return "confirm"

    with patch("asyncio.wait_for", side_effect=fake_wait_for):
        result = asyncio.run(request_hitl(
            session_id="s", cycle_index=0, symbol="XLK",
            side="buy", qty=10.0, risk_level="MEDIUM", risk_score=0.9,
            strategy="MOMENTUM", timeout_seconds=60, timeout_action="abort",
        ))

    assert result["action"] == "confirm"
    assert result["source"] == "human"
    assert result["latency_ms"] >= 0


def test_request_hitl_abort_input():
    from tools.coordinator.tools import request_hitl

    async def fake_wait_for(coro, timeout):
        return "abort"

    with patch("asyncio.wait_for", side_effect=fake_wait_for):
        result = asyncio.run(request_hitl(
            session_id="s", cycle_index=0, symbol="SPY",
            side="sell", qty=5.0, risk_level="HIGH", risk_score=1.5,
            strategy="MOMENTUM", timeout_seconds=30, timeout_action="confirm",
        ))

    assert result["action"] == "abort"
    assert result["source"] == "human"


def test_request_hitl_timeout_applies_action():
    from tools.coordinator.tools import request_hitl

    async def fake_wait_for(coro, timeout):
        import asyncio as _asyncio
        raise _asyncio.TimeoutError()

    with patch("asyncio.wait_for", side_effect=fake_wait_for):
        result = asyncio.run(request_hitl(
            session_id="s", cycle_index=1, symbol="QQQ",
            side="buy", qty=3.0, risk_level="LOW", risk_score=0.5,
            strategy="SECTOR_ROTATION", timeout_seconds=5, timeout_action="confirm",
        ))

    assert result["action"] == "confirm"
    assert result["source"] == "timeout"


def test_request_hitl_timeout_abort_action():
    from tools.coordinator.tools import request_hitl

    async def fake_wait_for(coro, timeout):
        import asyncio as _asyncio
        raise _asyncio.TimeoutError()

    with patch("asyncio.wait_for", side_effect=fake_wait_for):
        result = asyncio.run(request_hitl(
            session_id="s", cycle_index=0, symbol="IWM",
            side="sell", qty=2.0, risk_level="HIGH", risk_score=1.4,
            strategy="MEAN_REVERSION", timeout_seconds=10, timeout_action="abort",
        ))

    assert result["action"] == "abort"
    assert result["source"] == "timeout"
