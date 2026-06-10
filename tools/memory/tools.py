"""memory.* tools — 6 tools, coordinator scope only."""
from __future__ import annotations

from infra.observability import db_write_span, get_logger

logger = get_logger("tools.memory")


async def write_trade(
    session_id: str,
    cycle_index: int,
    symbol: str,
    strategy: str,
    side: str,
    qty: float,
    entry_price: float,
    order_id: str,
    optimist_level: str,
    pessimist_level: str,
    final_risk_level: str,
    risk_score: float,
    opt_win_rate: float,
    pess_win_rate: float,
    market_regime: str,
) -> dict:
    """Write a TradeRecord to SQLite BEFORE submitting the order (write-ahead pattern).

    Args:
        session_id: UUID of current session.
        cycle_index: Decision cycle number within this session.
        symbol: ETF ticker symbol being traded.
        strategy: Active strategy ('MOMENTUM', 'MEAN_REVERSION', 'SECTOR_ROTATION').
        side: Order side ('buy' or 'sell').
        qty: Number of shares.
        entry_price: Entry price per share.
        order_id: Alpaca order UUID.
        optimist_level: Risk level from optimist agent ('LOW', 'MEDIUM', 'HIGH').
        pessimist_level: Risk level from pessimist agent.
        final_risk_level: Synthesised risk level after debate.
        risk_score: Numeric risk score from synthesis formula.
        opt_win_rate: Optimist pairwise win rate at time of trade.
        pess_win_rate: Pessimist pairwise win rate at time of trade.
        market_regime: Current market regime string.

    Returns:
        dict with 'trade_id', 'written'.
    """
    logger.info("write_trade session_id=%s cycle=%d symbol=%s side=%s qty=%s", session_id, cycle_index, symbol, side, qty)
    import uuid
    from datetime import datetime
    from db.schema import write_trade_record
    from models.enums import MarketRegime, Strategy
    from models.memory import TradeRecord

    trade_id = str(uuid.uuid4())
    record = TradeRecord(
        id=trade_id,
        session_id=session_id,
        cycle_index=cycle_index,
        order_id=order_id,
        symbol=symbol,
        strategy=Strategy(strategy),
        market_regime=MarketRegime(market_regime),
        side=side,
        qty=qty,
        entry_price=entry_price,
        optimist_verdict=optimist_level,
        pessimist_verdict=pessimist_level,
        risk_level=final_risk_level,
        risk_score=risk_score,
        opt_win_rate_at_trade=opt_win_rate,
        pess_win_rate_at_trade=pess_win_rate,
        executed_at=datetime.utcnow(),
    )

    async with db_write_span("write_trade_record"):
        write_trade_record(record)

    return {"trade_id": trade_id, "written": True}


async def resolve_trade(trade_id: str, actual_pnl_pct: float) -> dict:
    """Resolve a trade outcome and update pairwise calibration stats.

    Args:
        trade_id: UUID of the trade to resolve.
        actual_pnl_pct: Actual realised P&L as a percentage.

    Returns:
        dict with 'trade_id', 'debate_winner', 'resolved'.
    """
    logger.info("resolve_trade trade_id=%s actual_pnl_pct=%s", trade_id, actual_pnl_pct)
    from db.schema import resolve_outcome

    async with db_write_span("resolve_outcome"):
        result = resolve_outcome(trade_id, actual_pnl_pct)

    winner = result.debate_winner.value if result.debate_winner else "tie"
    return {"trade_id": trade_id, "debate_winner": winner, "resolved": result.updated}


async def get_calibration(market_regime: str, strategy: str) -> dict:
    """Load pairwise win-rate calibration context for risk agent prompts.

    Args:
        market_regime: Current market regime ('BULL_TREND', 'BEAR_TREND', etc.).
        strategy: Active strategy ('MOMENTUM', 'MEAN_REVERSION', 'SECTOR_ROTATION').

    Returns:
        dict with 'has_data', 'opt_win_rate', 'pess_win_rate', 'opt_summary', 'pess_summary', 'trade_count'.
    """
    logger.info("get_calibration market_regime=%s strategy=%s", market_regime, strategy)
    from db.schema import get_calibration as _get_cal
    from models.enums import MarketRegime, Strategy

    regime = MarketRegime(market_regime)
    strat = Strategy(strategy)
    opt_cal = _get_cal("optimist", regime, strat)
    pess_cal = _get_cal("pessimist", regime, strat)

    return {
        "has_data": opt_cal.has_data or pess_cal.has_data,
        "opt_win_rate": opt_cal.win_rate,
        "pess_win_rate": pess_cal.win_rate,
        "opt_summary": opt_cal.formatted_summary,
        "pess_summary": pess_cal.formatted_summary,
        "trade_count": opt_cal.wins + opt_cal.losses,
    }


async def get_session_cycles(session_id: str) -> dict:
    """Load cycle history for an active session.

    Args:
        session_id: UUID of the session.

    Returns:
        dict with 'session_id' and 'cycles' (list of cycle records).
    """
    logger.info("get_session_cycles session_id=%s", session_id)
    from db.schema import _connect  # type: ignore[attr-defined]

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT cycle_index, outcome, abort_reason, abort_stage,
                   shortlisted_symbols, risk_level, trade_id, realised_pnl_pct
            FROM cycle_records WHERE session_id = ?
            ORDER BY cycle_index
            """,
            (session_id,),
        ).fetchall()

    cycles = [
        {
            "cycle_index": r["cycle_index"],
            "outcome": r["outcome"],
            "abort_reason": r["abort_reason"],
            "abort_stage": r["abort_stage"],
            "shortlisted_symbols": r["shortlisted_symbols"].split(",") if r["shortlisted_symbols"] else [],
            "risk_level": r["risk_level"],
            "trade_id": r["trade_id"],
            "realised_pnl_pct": r["realised_pnl_pct"],
        }
        for r in rows
    ]
    return {"session_id": session_id, "cycles": cycles}


async def get_unresolved_trades() -> dict:
    """Load all trades that are still pending outcome resolution.

    Returns:
        dict with 'trades' (list of {trade_id, symbol, order_id, opened_at}).
    """
    logger.info("get_unresolved_trades")
    from db.schema import get_unresolved_trades as _get_unresolved

    trades = _get_unresolved()
    return {
        "trades": [
            {
                "trade_id": t.id,
                "symbol": t.symbol,
                "order_id": t.order_id,
                "entry_price": t.entry_price,
                "side": t.side,
                "opened_at": t.executed_at.isoformat() if t.executed_at else None,
            }
            for t in trades
        ]
    }


async def record_cycle(
    session_id: str,
    cycle_index: int,
    outcome: str,
    shortlisted_symbols: list[str],
    risk_level: str,
    abort_reason: str,
    abort_stage: str,
    trade_id: str,
    realised_pnl_pct: float,
) -> dict:
    """Persist cycle metadata after each decision cycle completes or aborts.

    Args:
        session_id: UUID of the session.
        cycle_index: Cycle number (0-based).
        outcome: 'COMMITTED' or 'ABORTED'.
        shortlisted_symbols: List of symbols in candidate shortlist.
        risk_level: Final risk level for the cycle.
        abort_reason: Reason if aborted, empty string otherwise.
        abort_stage: Stage where abort occurred, empty string otherwise.
        trade_id: Trade UUID if committed, empty string otherwise.
        realised_pnl_pct: Realised P&L pct if known, 0.0 otherwise.

    Returns:
        dict with 'session_id', 'cycle_index', 'written'.
    """
    logger.info("record_cycle session_id=%s cycle=%d outcome=%s", session_id, cycle_index, outcome)
    from db.schema import _connect  # type: ignore[attr-defined]

    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO cycle_records
              (session_id, cycle_index, outcome, shortlisted_symbols, risk_level,
               abort_reason, abort_stage, trade_id, realised_pnl_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id, cycle_index, outcome,
                ",".join(shortlisted_symbols),
                risk_level, abort_reason, abort_stage,
                trade_id if trade_id else None,
                realised_pnl_pct,
            ),
        )

    return {"session_id": session_id, "cycle_index": cycle_index, "written": True}
