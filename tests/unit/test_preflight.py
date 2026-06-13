"""Unit tests for agent/preflight.py — deterministic pre-flight checks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch


def _expires(delta_seconds: int) -> datetime:
    """Return a UTC datetime offset by delta_seconds from now."""
    return datetime.now(UTC) + timedelta(seconds=delta_seconds)


_MARKET_OPEN = {"is_open": True, "next_open": None, "next_close": "2026-01-01T16:00:00"}
_MARKET_CLOSED = {
    "is_open": False,
    "next_open": "2026-01-02T09:30:00",
    "next_close": None,
}
_LOSS_OK = {"breached": False, "warning": False, "consumed_pct": 10.0, "remaining_eur": 450.0}
_LOSS_WARN = {"breached": False, "warning": True, "consumed_pct": 85.0, "remaining_eur": 75.0}
_LOSS_BREACHED = {
    "breached": True,
    "warning": True,
    "consumed_pct": 105.0,
    "remaining_eur": -25.0,
}
_RESOLVE_OK = {"resolved_count": 2, "failed_count": 0, "details": []}


def _run(coro):
    return asyncio.run(coro)


# ── session expiry ─────────────────────────────────────────────────────────────


def test_preflight_session_expired():
    from agent.preflight import run_preflight

    result = _run(
        run_preflight(
            session_id="s1",
            session_expires_at=_expires(-1),  # already past
            exchange_tz="America/New_York",
            allow_closed_market=False,
            loss_limit_eur=500.0,
            session_realised_pnl_eur=0.0,
            unrealised_pnl_eur=0.0,
        )
    )
    assert result.ok is False
    assert result.abort_stage == "session_expired"
    assert "SESSION EXPIRED" in result.report


def test_preflight_not_expired_continues():
    from agent.preflight import run_preflight

    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s2",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is True


# ── market hours ───────────────────────────────────────────────────────────────


def test_preflight_market_closed_no_override():
    from agent.preflight import run_preflight

    with patch(
        "agent.preflight.get_market_status",
        new=AsyncMock(return_value=_MARKET_CLOSED),
    ):
        result = _run(
            run_preflight(
                session_id="s3",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is False
    assert result.abort_stage == "market_closed"
    assert "MARKET CLOSED" in result.report
    assert result.next_open == "2026-01-02T09:30:00"


def test_preflight_market_closed_with_override_proceeds():
    from agent.preflight import run_preflight

    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_CLOSED),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s4",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=True,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is True
    assert result.market_is_open is False
    assert any("override" in m.lower() for m in result.messages)


def test_preflight_market_open_proceeds():
    from agent.preflight import run_preflight

    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s5",
                session_expires_at=_expires(3600),
                exchange_tz="Europe/Berlin",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is True
    assert result.market_is_open is True


# ── loss limit ────────────────────────────────────────────────────────────────


def test_preflight_loss_limit_breached():
    from agent.preflight import run_preflight

    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_BREACHED),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s6",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=-525.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is False
    assert result.abort_stage == "loss_limit"
    assert "LOSS LIMIT BREACHED" in result.report


def test_preflight_loss_limit_warning_continues():
    from agent.preflight import run_preflight

    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_WARN),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s7",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=-425.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is True
    assert any("WARNING" in m for m in result.messages)


# ── resolve unresolved trades ─────────────────────────────────────────────────


def test_preflight_resolves_trades_on_first_run():
    from agent.preflight import run_preflight

    resolve_mock = AsyncMock(return_value=_RESOLVE_OK)
    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
        patch("agent.preflight.resolve_unresolved_trades", resolve_mock),
    ):
        result = _run(
            run_preflight(
                session_id="s8",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=True,
            )
        )
    assert result.ok is True
    assert result.resolved_count == 2
    resolve_mock.assert_awaited_once()


def test_preflight_skips_resolve_on_subsequent_runs():
    from agent.preflight import run_preflight

    resolve_mock = AsyncMock(return_value=_RESOLVE_OK)
    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
        patch("agent.preflight.resolve_unresolved_trades", resolve_mock),
    ):
        result = _run(
            run_preflight(
                session_id="s9",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is True
    resolve_mock.assert_not_awaited()


def test_preflight_resolve_error_is_nonfatal():
    from agent.preflight import run_preflight

    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
        patch(
            "agent.preflight.resolve_unresolved_trades",
            new=AsyncMock(side_effect=RuntimeError("alpaca down")),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s10",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=True,
            )
        )
    assert result.ok is True


# ── result fields ─────────────────────────────────────────────────────────────


def test_preflight_result_consumed_pct():
    from agent.preflight import run_preflight

    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s11",
                session_expires_at=_expires(3600),
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=-50.0,
                unrealised_pnl_eur=10.0,
                resolve_trades=False,
            )
        )
    assert result.ok is True
    assert result.loss_limit_consumed_pct == 10.0


def test_preflight_naive_expires_at_handled():
    """Naive (tz-unaware) session_expires_at must not crash."""
    from agent.preflight import run_preflight

    naive_future = datetime.utcnow() + timedelta(hours=1)
    with (
        patch(
            "agent.preflight.get_market_status",
            new=AsyncMock(return_value=_MARKET_OPEN),
        ),
        patch(
            "agent.preflight.check_loss_limit",
            new=AsyncMock(return_value=_LOSS_OK),
        ),
    ):
        result = _run(
            run_preflight(
                session_id="s12",
                session_expires_at=naive_future,
                exchange_tz="America/New_York",
                allow_closed_market=False,
                loss_limit_eur=500.0,
                session_realised_pnl_eur=0.0,
                unrealised_pnl_eur=0.0,
                resolve_trades=False,
            )
        )
    assert result.ok is True
