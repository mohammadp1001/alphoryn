"""
SQLite schema creation and all database queries.
Single connection helper — this is a single-user CLI, no connection pooling needed.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from config import DB_PATH, DEBATE_TIE_THRESHOLD_PCT
from models.enums import CycleOutcome, DebateWinner, MarketRegime, Strategy
from models.memory import AgentPairwise, CalibrationContext, CycleRecord, TradeRecord, UpdateResult

_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    closed_at       TEXT,
    strategy        TEXT NOT NULL,
    market_regime   TEXT,
    mode            TEXT NOT NULL,
    realised_pnl    REAL DEFAULT 0.0,
    cycle_count     INTEGER DEFAULT 0,
    outcome         TEXT
);

CREATE TABLE IF NOT EXISTS trade_records (
    id                      TEXT PRIMARY KEY,
    session_id              TEXT NOT NULL,
    cycle_index             INTEGER DEFAULT 0,
    order_id                TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    strategy                TEXT NOT NULL,
    market_regime           TEXT NOT NULL,
    side                    TEXT NOT NULL DEFAULT 'buy',
    qty                     REAL NOT NULL,
    entry_price             REAL DEFAULT 0.0,
    optimist_verdict        TEXT NOT NULL,
    pessimist_verdict       TEXT NOT NULL,
    risk_level              TEXT NOT NULL,
    risk_score              REAL DEFAULT 0.0,
    opt_win_rate_at_trade   REAL DEFAULT 0.5,
    pess_win_rate_at_trade  REAL DEFAULT 0.5,
    filled_avg_price        REAL,
    executed_at             TEXT NOT NULL,
    actual_pnl_pct          REAL,
    debate_winner           TEXT,
    outcome_resolved        INTEGER DEFAULT 0,
    outcome_timed_out       INTEGER DEFAULT 0,
    resolved_at             TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS cycle_records (
    session_id          TEXT NOT NULL,
    cycle_index         INTEGER NOT NULL,
    outcome             TEXT NOT NULL,
    shortlisted_symbols TEXT,
    risk_level          TEXT,
    abort_reason        TEXT,
    abort_stage         TEXT,
    trade_id            TEXT,
    realised_pnl_pct    REAL DEFAULT 0.0,
    PRIMARY KEY (session_id, cycle_index),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS agent_pairwise (
    agent           TEXT NOT NULL,
    market_regime   TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    ties            INTEGER DEFAULT 0,
    last_updated    TEXT NOT NULL,
    PRIMARY KEY (agent, market_regime, strategy)
);

CREATE TABLE IF NOT EXISTS regime_stats (
    market_regime   TEXT PRIMARY KEY,
    total_trades    INTEGER DEFAULT 0,
    win_rate        REAL DEFAULT 0.0,
    avg_pnl         REAL DEFAULT 0.0,
    best_strategy   TEXT,
    last_seen       TEXT NOT NULL
);
"""


def init_db(path: Path = DB_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.executescript(_DDL)


@contextmanager
def _connect(path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    if path is None:
        path = DB_PATH  # runtime lookup — allows monkeypatching in tests
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Sessions ──────────────────────────────────────────────────────────────────

def upsert_session(
    session_id: str,
    strategy: str,
    mode: str,
    market_regime: str | None = None,
    started_at: datetime | None = None,
) -> None:
    now = (started_at or datetime.utcnow()).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, started_at, strategy, mode, market_regime)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET market_regime = excluded.market_regime
            """,
            (session_id, now, strategy, mode, market_regime),
        )


def close_session(session_id: str, outcome: str, realised_pnl: float, cycle_count: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET closed_at = ?, outcome = ?, realised_pnl = ?, cycle_count = ?
            WHERE id = ?
            """,
            (datetime.utcnow().isoformat(), outcome, realised_pnl, cycle_count, session_id),
        )


# ── Trade records ─────────────────────────────────────────────────────────────

def write_trade_record(record: TradeRecord) -> None:
    """Write-ahead: called synchronously before submitting the order."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_records (
                id, session_id, cycle_index, order_id, symbol, strategy,
                market_regime, side, qty, entry_price,
                optimist_verdict, pessimist_verdict, risk_level,
                risk_score, opt_win_rate_at_trade, pess_win_rate_at_trade,
                filled_avg_price, executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id, record.session_id, record.cycle_index,
                record.order_id, record.symbol,
                record.strategy.value if hasattr(record.strategy, "value") else record.strategy,
                record.market_regime.value if hasattr(record.market_regime, "value") else record.market_regime,
                record.side, record.qty, record.entry_price,
                record.optimist_verdict, record.pessimist_verdict, record.risk_level,
                record.risk_score, record.opt_win_rate_at_trade, record.pess_win_rate_at_trade,
                record.filled_avg_price, record.executed_at.isoformat(),
            ),
        )


def resolve_outcome(trade_id: str, actual_pnl_pct: float) -> UpdateResult:
    """
    Fill outcome fields on a TradeRecord and update agent_pairwise win rates.
    Called by the webhook handler or session-start poller.
    """
    winner = _determine_winner(actual_pnl_pct)

    with _connect() as conn:
        conn.execute(
            """
            UPDATE trade_records
            SET actual_pnl_pct = ?, debate_winner = ?,
                outcome_resolved = 1, resolved_at = ?
            WHERE id = ?
            """,
            (actual_pnl_pct, winner.value, datetime.utcnow().isoformat(), trade_id),
        )

        row = conn.execute(
            "SELECT market_regime, strategy FROM trade_records WHERE id = ?",
            (trade_id,),
        ).fetchone()

        if row:
            _update_pairwise(conn, winner, row["market_regime"], row["strategy"])
            _update_regime_stats(conn, row["market_regime"], row["strategy"], actual_pnl_pct)

    return UpdateResult(
        trade_id=trade_id,
        updated=True,
        debate_winner=winner,
        actual_pnl_pct=actual_pnl_pct,
    )


def mark_outcome_timed_out(trade_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE trade_records SET outcome_timed_out = 1 WHERE id = ?",
            (trade_id,),
        )


def get_unresolved_trades(session_id: str | None = None) -> list[TradeRecord]:
    """Returns TradeRecord objects with outcome_resolved=0 and outcome_timed_out=0."""
    with _connect() as conn:
        if session_id:
            rows = conn.execute(
                """SELECT * FROM trade_records
                   WHERE outcome_resolved = 0 AND outcome_timed_out = 0
                   AND session_id = ?""",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM trade_records
                   WHERE outcome_resolved = 0 AND outcome_timed_out = 0"""
            ).fetchall()

    return [
        TradeRecord(
            id=r["id"],
            session_id=r["session_id"],
            cycle_index=r["cycle_index"] or 0,
            order_id=r["order_id"],
            symbol=r["symbol"],
            strategy=Strategy(r["strategy"]),
            market_regime=MarketRegime(r["market_regime"]),
            side=r["side"] or "buy",
            qty=r["qty"],
            entry_price=r["entry_price"] or 0.0,
            optimist_verdict=r["optimist_verdict"],
            pessimist_verdict=r["pessimist_verdict"],
            risk_level=r["risk_level"],
            risk_score=r["risk_score"] or 0.0,
            opt_win_rate_at_trade=r["opt_win_rate_at_trade"] or 0.5,
            pess_win_rate_at_trade=r["pess_win_rate_at_trade"] or 0.5,
            filled_avg_price=r["filled_avg_price"],
            executed_at=datetime.fromisoformat(r["executed_at"]),
            actual_pnl_pct=r["actual_pnl_pct"],
            outcome_resolved=bool(r["outcome_resolved"]),
            outcome_timed_out=bool(r["outcome_timed_out"]),
        )
        for r in rows
    ]


# ── Calibration ───────────────────────────────────────────────────────────────

def get_calibration(
    agent: str, market_regime: MarketRegime, strategy: Strategy
) -> CalibrationContext:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_pairwise WHERE agent = ? AND market_regime = ? AND strategy = ?",
            (agent, market_regime.value, strategy.value),
        ).fetchone()

    if row is None or (row["wins"] + row["losses"]) < 1:
        return CalibrationContext(
            agent=agent,
            market_regime=market_regime,
            strategy=strategy,
            win_rate=0.5,
            wins=0,
            losses=0,
            has_data=False,
            formatted_summary=(
                f"[CALIBRATION] No historical data yet for {agent} in "
                f"{market_regime}/{strategy}. Starting at equal weight."
            ),
        )

    wins, losses, ties = row["wins"], row["losses"], row["ties"]
    total = wins + losses
    win_rate = wins / total
    return CalibrationContext(
        agent=agent,
        market_regime=market_regime,
        strategy=strategy,
        win_rate=win_rate,
        wins=wins,
        losses=losses,
        has_data=True,
        formatted_summary=(
            f"[CALIBRATION] {agent.upper()} in {market_regime}/{strategy}: "
            f"win rate {win_rate:.0%} over {total} trades "
            f"({wins}W / {losses}L / {ties}T). Adjust confidence accordingly."
        ),
    )


# ── Cycle history ─────────────────────────────────────────────────────────────

def get_cycle_history(session_id: str) -> list[CycleRecord]:
    """Reconstructed from trade_records; cycles without a trade are stored in PlanState only."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_records WHERE session_id = ? ORDER BY executed_at",
            (session_id,),
        ).fetchall()

    return [
        CycleRecord(
            cycle_index=i,
            outcome=CycleOutcome.COMMITTED,
            trade_id=r["id"],
            shortlisted_symbols=[r["symbol"]],
            risk_level=r["risk_level"],
            realised_pnl_pct=r["actual_pnl_pct"],
        )
        for i, r in enumerate(rows)
    ]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _determine_winner(pnl_pct: float) -> DebateWinner:
    if pnl_pct < 0:
        return DebateWinner.PESSIMIST
    if pnl_pct >= DEBATE_TIE_THRESHOLD_PCT:
        return DebateWinner.OPTIMIST
    return DebateWinner.TIE


def _update_pairwise(
    conn: sqlite3.Connection,
    winner: DebateWinner,
    market_regime: str,
    strategy: str,
) -> None:
    now = datetime.utcnow().isoformat()
    for agent in ("optimist", "pessimist"):
        if winner == DebateWinner.TIE:
            delta = {"optimist": (0, 0, 1), "pessimist": (0, 0, 1)}[agent]
        elif winner == DebateWinner.OPTIMIST:
            delta = {"optimist": (1, 0, 0), "pessimist": (0, 1, 0)}[agent]
        else:
            delta = {"optimist": (0, 1, 0), "pessimist": (1, 0, 0)}[agent]

        w, l, t = delta
        conn.execute(
            """
            INSERT INTO agent_pairwise (agent, market_regime, strategy, wins, losses, ties, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent, market_regime, strategy) DO UPDATE SET
                wins = wins + excluded.wins,
                losses = losses + excluded.losses,
                ties = ties + excluded.ties,
                last_updated = excluded.last_updated
            """,
            (agent, market_regime, strategy, w, l, t, now),
        )


def _update_regime_stats(
    conn: sqlite3.Connection,
    market_regime: str,
    strategy: str,
    pnl_pct: float,
) -> None:
    now = datetime.utcnow().isoformat()
    existing = conn.execute(
        "SELECT * FROM regime_stats WHERE market_regime = ?", (market_regime,)
    ).fetchone()

    if existing is None:
        win_rate = 1.0 if pnl_pct >= DEBATE_TIE_THRESHOLD_PCT else 0.0
        conn.execute(
            """INSERT INTO regime_stats
               (market_regime, total_trades, win_rate, avg_pnl, best_strategy, last_seen)
               VALUES (?, 1, ?, ?, ?, ?)""",
            (market_regime, win_rate, pnl_pct, strategy, now),
        )
    else:
        n = existing["total_trades"]
        new_n = n + 1
        new_avg = (existing["avg_pnl"] * n + pnl_pct) / new_n
        wins_so_far = round(existing["win_rate"] * n)
        new_win = 1 if pnl_pct >= DEBATE_TIE_THRESHOLD_PCT else 0
        new_win_rate = (wins_so_far + new_win) / new_n
        conn.execute(
            """UPDATE regime_stats SET
               total_trades = ?, win_rate = ?, avg_pnl = ?, last_seen = ?
               WHERE market_regime = ?""",
            (new_n, new_win_rate, new_avg, now, market_regime),
        )
