"""coordinator.* tools — 8 tools, coordinator agent scope."""
from __future__ import annotations

import asyncio
from datetime import datetime

from infra.observability import get_logger

logger = get_logger("tools.coordinator")


async def request_hitl(
    session_id: str,
    cycle_index: int,
    symbol: str,
    side: str,
    qty: float,
    risk_level: str,
    risk_score: float,
    strategy: str,
    timeout_seconds: int,
    timeout_action: str,
) -> dict:
    """Pause execution and prompt the human operator for confirmation.

    Args:
        session_id: UUID of current session.
        cycle_index: Current decision cycle index.
        symbol: ETF symbol being traded.
        side: 'buy' or 'sell'.
        qty: Number of shares proposed.
        risk_level: Synthesised risk level ('LOW', 'MEDIUM', 'HIGH').
        risk_score: Numeric risk score (0-2).
        strategy: Active strategy name.
        timeout_seconds: Seconds to wait before applying timeout_action.
        timeout_action: 'abort' or 'confirm' on timeout.

    Returns:
        dict with 'action' ('confirm'|'abort'), 'source' ('human'|'timeout'), 'latency_ms'.
    """
    logger.info("request_hitl session_id=%s cycle=%d symbol=%s side=%s qty=%s risk=%s", session_id, cycle_index, symbol, side, qty, risk_level)
    from infra.observability import hitl_span

    start = datetime.utcnow()
    prompt = (
        f"\n{'='*60}\n"
        f"[HITL] Cycle {cycle_index} — {symbol}\n"
        f"  Action  : {side.upper()} {qty} shares\n"
        f"  Strategy: {strategy}\n"
        f"  Risk    : {risk_level} (score={risk_score:.3f})\n"
        f"  Session : {session_id}\n"
        f"Type 'confirm' to proceed or 'abort' to skip [{timeout_action} in {timeout_seconds}s]: "
    )

    async with hitl_span(session_id, cycle_index, risk_level):
        try:
            loop = asyncio.get_event_loop()
            user_input = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: input(prompt).strip().lower()),
                timeout=float(timeout_seconds),
            )
            action = "confirm" if user_input == "confirm" else "abort"
            source = "human"
        except asyncio.TimeoutError:
            action = timeout_action
            source = "timeout"
            print(f"\n[HITL] Timeout — applying '{action}'")

    latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    return {"action": action, "source": source, "latency_ms": latency_ms}


async def check_loss_limit(
    session_realised_pnl_eur: float,
    loss_limit_eur: float,
    unrealised_pnl_eur: float,
) -> dict:
    """Check whether realised loss limit has been breached or is near warning threshold.

    Args:
        session_realised_pnl_eur: Cumulative realised P&L for this session in EUR (negative = loss).
        loss_limit_eur: Maximum loss allowed in EUR (positive value, e.g. 500.0).
        unrealised_pnl_eur: Current unrealised P&L in EUR (for context only, NOT counted).

    Returns:
        dict with 'breached', 'warning', 'consumed_pct', 'remaining_eur'.
    """
    logger.info("check_loss_limit realised_pnl=%s limit=%s", session_realised_pnl_eur, loss_limit_eur)
    consumed = -session_realised_pnl_eur  # positive = we have consumed some loss budget
    consumed_pct = consumed / loss_limit_eur * 100 if loss_limit_eur > 0 else 0.0
    remaining = loss_limit_eur - consumed

    return {
        "breached": consumed >= loss_limit_eur,
        "warning": consumed_pct >= 80.0,
        "consumed_pct": round(consumed_pct, 2),
        "remaining_eur": round(remaining, 2),
        "unrealised_pnl_eur": unrealised_pnl_eur,
    }


async def select_shortlist(
    ranked_signals: list[dict],
    shortlist_n: int,
    strategy: str,
) -> dict:
    """Select the top-N candidate ETFs from ranked analysis signals.

    Args:
        ranked_signals: List of {symbol, combined_score, ...} from rank_by_momentum.
        shortlist_n: Number of candidates to shortlist (default 2, max 5).
        strategy: Active strategy (used for selection weighting).

    Returns:
        dict with 'shortlisted' (list of {symbol, score}), 'n', 'strategy'.
    """
    logger.info("select_shortlist n_signals=%d shortlist_n=%d strategy=%s", len(ranked_signals), shortlist_n, strategy)
    from config import MAX_SHORTLIST_N

    n = min(shortlist_n, MAX_SHORTLIST_N)
    top = sorted(ranked_signals, key=lambda x: x.get("combined_score", 0), reverse=True)[:n]

    shortlisted = [
        {"symbol": s["symbol"], "combined_score": s.get("combined_score", 0)}
        for s in top
    ]
    return {"shortlisted": shortlisted, "n": len(shortlisted), "strategy": strategy}


async def synthesise_risk(
    optimist_level: str,
    optimist_reasoning: str,
    pessimist_level: str,
    pessimist_reasoning: str,
    opt_win_rate: float,
    pess_win_rate: float,
) -> dict:
    """Apply ADR 0001 formula to synthesise a final risk assessment from debate verdicts.

    Args:
        optimist_level: Risk level from optimist ('LOW', 'MEDIUM', 'HIGH').
        optimist_reasoning: Optimist's justification text.
        pessimist_level: Risk level from pessimist.
        pessimist_reasoning: Pessimist's justification text.
        opt_win_rate: Optimist pairwise win rate (0.0-1.0).
        pess_win_rate: Pessimist pairwise win rate (0.0-1.0).

    Returns:
        dict with 'risk_level', 'risk_score', 'debate_winner', 'synthesis_reasoning'.
    """
    logger.info("synthesise_risk opt=%s pess=%s opt_win_rate=%s pess_win_rate=%s", optimist_level, pessimist_level, opt_win_rate, pess_win_rate)
    from models.enums import RiskLevel, DebateWinner
    from models.risk import AgentVerdict
    from config import (PESSIMIST_OVERRIDE_WIN_RATE, RISK_HIGH_THRESHOLD, RISK_LOW_THRESHOLD,
                        DEBATE_TIE_THRESHOLD_PCT)

    level_map = {"LOW": 0.5, "MEDIUM": 1.0, "HIGH": 1.5}
    opt_num = level_map.get(optimist_level, 1.0)
    pess_num = level_map.get(pessimist_level, 1.0)

    total_weight = opt_win_rate + pess_win_rate
    if total_weight == 0:
        score = 1.0
    else:
        score = (opt_num * opt_win_rate + pess_num * pess_win_rate) / total_weight

    # Determine base risk level from score
    if score < RISK_LOW_THRESHOLD:
        risk_level = "LOW"
    elif score > RISK_HIGH_THRESHOLD:
        risk_level = "HIGH"
    else:
        risk_level = "MEDIUM"

    # Asymmetric pessimist override
    if pessimist_level == "HIGH" and pess_win_rate > PESSIMIST_OVERRIDE_WIN_RATE:
        risk_level = "HIGH"

    # Determine debate winner
    if pessimist_level == "HIGH":
        debate_winner = "pessimist"
    elif optimist_level != "HIGH" and score >= RISK_LOW_THRESHOLD:
        pnl_threshold = DEBATE_TIE_THRESHOLD_PCT / 100
        debate_winner = "optimist" if score <= RISK_LOW_THRESHOLD + 0.3 else "tie"
    else:
        debate_winner = "tie"

    synthesis = (
        f"Score={score:.3f} (opt={opt_num}×{opt_win_rate:.2f} + "
        f"pess={pess_num}×{pess_win_rate:.2f}) → {risk_level}"
    )
    return {
        "risk_level": risk_level,
        "risk_score": round(score, 4),
        "debate_winner": debate_winner,
        "synthesis_reasoning": synthesis,
    }


async def resolve_unresolved_trades() -> dict:
    """Poll Alpaca for outcomes on all unresolved trades (session-start routine).

    Returns:
        dict with 'resolved_count', 'failed_count', 'details'.
    """
    logger.info("resolve_unresolved_trades")
    import os
    from db.schema import get_unresolved_trades, resolve_outcome

    unresolved = get_unresolved_trades()
    if not unresolved:
        return {"resolved_count": 0, "failed_count": 0, "details": []}

    from alpaca.trading.client import TradingClient  # type: ignore[import]
    from infra.rate_limiter import acquire_alpaca_trading

    client = TradingClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_API_SECRET"],
        paper=True,
    )

    resolved_count = 0
    failed_count = 0
    details = []

    for trade in unresolved:
        try:
            await acquire_alpaca_trading()
            order = client.get_order_by_id(trade.order_id)
            filled_price = float(order.filled_avg_price or 0)
            entry_price = trade.entry_price or 0.0

            if filled_price > 0 and entry_price > 0:
                pnl_pct = (filled_price - entry_price) / entry_price * 100
                if str(trade.side).lower() == "sell":
                    pnl_pct = -pnl_pct
                resolve_outcome(trade.id, pnl_pct)
                resolved_count += 1
                details.append({"trade_id": trade.id, "status": "resolved",
                                "pnl_pct": round(pnl_pct, 4)})
            else:
                failed_count += 1
                details.append({"trade_id": trade.id, "status": "unresolvable",
                                "reason": "no fill price"})
        except Exception as exc:
            failed_count += 1
            details.append({"trade_id": trade.id, "status": "error", "reason": str(exc)})

    return {"resolved_count": resolved_count, "failed_count": failed_count, "details": details}


async def update_plan_state(
    session_id: str,
    field: str,
    value: str,
) -> dict:
    """Update a specific field on the session plan state in ADK session store.

    Args:
        session_id: UUID of current session.
        field: PlanState field name to update (e.g. 'market_regime', 'cycle_index').
        value: String-serialised new value.

    Returns:
        dict with 'session_id', 'field', 'updated'.
    """
    logger.info("update_plan_state session_id=%s field=%s", session_id, field)
    # PlanState is carried in ADK session state — this tool signals intent
    # The coordinator reads this and applies it via callback_context.state
    return {"session_id": session_id, "field": field, "value": value, "updated": True}


async def get_session_summary(session_id: str) -> dict:
    """Build a human-readable summary of session progress.

    Args:
        session_id: UUID of the session.

    Returns:
        dict with 'session_id', 'cycle_count', 'committed_count', 'aborted_count',
                  'session_realised_pnl_eur', 'loss_limit_consumed_pct'.
    """
    logger.info("get_session_summary session_id=%s", session_id)
    from db.schema import _connect  # type: ignore[attr-defined]

    with _connect() as conn:
        rows = conn.execute(
            "SELECT outcome, realised_pnl_pct FROM cycle_records WHERE session_id = ?",
            (session_id,),
        ).fetchall()

    committed = [r for r in rows if r[0] == "COMMITTED"]
    aborted = [r for r in rows if r[0] == "ABORTED"]
    realised_pnl = sum(r[1] or 0.0 for r in committed)

    return {
        "session_id": session_id,
        "cycle_count": len(rows),
        "committed_count": len(committed),
        "aborted_count": len(aborted),
        "session_realised_pnl_eur": round(realised_pnl, 4),
        "loss_limit_consumed_pct": 0.0,  # coordinator tracks absolute EUR
    }


async def abort_cycle(
    session_id: str,
    cycle_index: int,
    reason: str,
    stage: str,
) -> dict:
    """Record a cycle abort and return CycleOutcome=ABORTED.

    Args:
        session_id: UUID of the session.
        cycle_index: Current cycle index.
        reason: Human-readable abort reason.
        stage: Stage where abort occurred (e.g. 'risk_HIGH', 'hitl_abort', 'loss_limit').

    Returns:
        dict with 'outcome' ('ABORTED'), 'reason', 'stage'.
    """
    logger.info("abort_cycle session_id=%s cycle=%d stage=%s reason=%s", session_id, cycle_index, stage, reason)
    return {"outcome": "ABORTED", "reason": reason, "stage": stage,
            "session_id": session_id, "cycle_index": cycle_index}
