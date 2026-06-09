"""Integration tests for loss limit checking logic."""
from __future__ import annotations

import asyncio

import pytest


def test_loss_limit_not_breached_when_no_loss() -> None:
    from tools.coordinator.tools import check_loss_limit

    result = asyncio.run(check_loss_limit(0.0, 500.0, 0.0))
    assert result["breached"] is False
    assert result["warning"] is False
    assert result["consumed_pct"] == 0.0
    assert result["remaining_eur"] == 500.0


def test_loss_limit_warning_at_80_pct() -> None:
    from tools.coordinator.tools import check_loss_limit

    result = asyncio.run(check_loss_limit(-400.0, 500.0, 0.0))  # 400 loss of 500 limit
    assert result["warning"] is True
    assert result["breached"] is False
    assert abs(result["consumed_pct"] - 80.0) < 0.1


def test_loss_limit_breached_at_100_pct() -> None:
    from tools.coordinator.tools import check_loss_limit

    result = asyncio.run(check_loss_limit(-500.0, 500.0, 0.0))
    assert result["breached"] is True
    assert result["remaining_eur"] == 0.0


def test_loss_limit_breached_beyond_100_pct() -> None:
    from tools.coordinator.tools import check_loss_limit

    result = asyncio.run(check_loss_limit(-600.0, 500.0, 0.0))
    assert result["breached"] is True
    assert result["remaining_eur"] < 0


def test_unrealised_pnl_not_counted_in_limit() -> None:
    from tools.coordinator.tools import check_loss_limit

    # Large unrealised loss should not breach realised limit
    result = asyncio.run(check_loss_limit(0.0, 500.0, -1000.0))
    assert result["breached"] is False
    assert result["unrealised_pnl_eur"] == -1000.0
