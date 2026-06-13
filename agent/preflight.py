"""Deterministic pre-flight checks executed before the coordinator agent starts each turn.

Sequence
--------
0.  Session expiry   — abort if wall-clock has passed session_expires_at.
    Market hours     — call get_market_status; gate on allow_closed_market flag.
1.  Loss limit       — call check_loss_limit; abort if breached.
2.  Resolve trades   — call resolve_unresolved_trades (once per session start).

Returns a PreflightResult.  ok=False means the caller must end the session;
abort_stage and abort_reason carry the structured reason for DB/logging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from infra.observability import get_logger
from tools.coordinator.tools import check_loss_limit, get_market_status, resolve_unresolved_trades

logger = get_logger("agent.preflight")


@dataclass
class PreflightResult:
    ok: bool
    abort_stage: str = ""
    abort_reason: str = ""
    report: str = ""
    # collateral data from successful checks
    market_is_open: bool = True
    next_open: str | None = None
    loss_limit_consumed_pct: float = 0.0
    resolved_count: int = 0
    messages: list[str] = field(default_factory=list)


async def run_preflight(
    *,
    session_id: str,
    session_expires_at: datetime,
    exchange_tz: str,
    allow_closed_market: bool,
    loss_limit_eur: float,
    session_realised_pnl_eur: float,
    unrealised_pnl_eur: float,
    resolve_trades: bool = True,
) -> PreflightResult:
    """Run all pre-flight checks in order.  Returns PreflightResult.

    Args:
        session_id: Active session UUID (for logging).
        session_expires_at: UTC datetime when the session duration elapses.
        exchange_tz: IANA timezone string for market hours check.
        allow_closed_market: When True, closed market is a warning, not an abort.
        loss_limit_eur: Maximum loss budget in EUR (positive value).
        session_realised_pnl_eur: Cumulative realised P&L this session (negative = loss).
        unrealised_pnl_eur: Current unrealised P&L (informational only).
        resolve_trades: Run resolve_unresolved_trades step (False on subsequent cycles).
    """
    messages: list[str] = []

    # ── 0a. Session expiry ────────────────────────────────────────────────────
    now_utc = datetime.now(UTC)
    expires_aware = session_expires_at
    if expires_aware.tzinfo is None:
        expires_aware = session_expires_at.replace(tzinfo=UTC)

    if now_utc >= expires_aware:
        msg = f"SESSION EXPIRED — duration elapsed (expires_at={expires_aware.isoformat()})."
        logger.warning("preflight session_expired session_id=%s", session_id)
        return PreflightResult(
            ok=False,
            abort_stage="session_expired",
            abort_reason="Session duration elapsed",
            report=msg,
            messages=[msg],
        )

    # ── 0b. Market hours ──────────────────────────────────────────────────────
    market = await get_market_status(timezone=exchange_tz)
    is_open: bool = market.get("is_open", True)
    next_open: str | None = market.get("next_open")

    if not is_open:
        if not allow_closed_market:
            msg = f"MARKET CLOSED — next open: {next_open} ({exchange_tz})."
            logger.warning(
                "preflight market_closed session_id=%s next_open=%s", session_id, next_open
            )
            return PreflightResult(
                ok=False,
                abort_stage="market_closed",
                abort_reason="Market is closed",
                report=msg,
                market_is_open=False,
                next_open=next_open,
                messages=[msg],
            )
        override_msg = "MARKET CLOSED (override active) — proceeding."
        logger.info("preflight market_closed_override session_id=%s", session_id)
        messages.append(override_msg)
    else:
        messages.append(f"Market OPEN ({exchange_tz}).")

    # ── 1. Loss limit ─────────────────────────────────────────────────────────
    loss = await check_loss_limit(
        session_realised_pnl_eur=session_realised_pnl_eur,
        loss_limit_eur=loss_limit_eur,
        unrealised_pnl_eur=unrealised_pnl_eur,
    )
    consumed_pct: float = loss.get("consumed_pct", 0.0)

    if loss.get("breached"):
        msg = (
            f"LOSS LIMIT BREACHED — consumed {consumed_pct:.1f}% of {loss_limit_eur:.0f} EUR limit."
        )
        logger.warning(
            "preflight loss_limit_breached session_id=%s consumed_pct=%.1f",
            session_id,
            consumed_pct,
        )
        return PreflightResult(
            ok=False,
            abort_stage="loss_limit",
            abort_reason=f"Loss limit breached ({consumed_pct:.1f}% consumed)",
            report=msg,
            market_is_open=is_open,
            next_open=next_open,
            loss_limit_consumed_pct=consumed_pct,
            messages=messages + [msg],
        )

    if loss.get("warning"):
        warn_msg = f"LOSS WARNING — {consumed_pct:.1f}% of loss limit consumed."
        logger.warning(
            "preflight loss_limit_warning session_id=%s consumed_pct=%.1f",
            session_id,
            consumed_pct,
        )
        messages.append(warn_msg)
    else:
        messages.append(f"Loss limit OK — {consumed_pct:.1f}% consumed.")

    # ── 2. Resolve unresolved trades ──────────────────────────────────────────
    resolved_count = 0
    if resolve_trades:
        try:
            resolution = await resolve_unresolved_trades()
            resolved_count = resolution.get("resolved_count", 0)
            failed_count = resolution.get("failed_count", 0)
            messages.append(f"Unresolved trades: resolved={resolved_count} failed={failed_count}.")
            logger.info(
                "preflight resolve_trades resolved=%d failed=%d session_id=%s",
                resolved_count,
                failed_count,
                session_id,
            )
        except Exception as exc:
            # Non-fatal — log and continue
            logger.warning(
                "preflight resolve_trades error=%s session_id=%s",
                exc,
                session_id,
                exc_info=True,
            )
            messages.append(f"Unresolved trade resolution skipped: {exc}")

    return PreflightResult(
        ok=True,
        market_is_open=is_open,
        next_open=next_open,
        loss_limit_consumed_pct=consumed_pct,
        resolved_count=resolved_count,
        messages=messages,
    )
