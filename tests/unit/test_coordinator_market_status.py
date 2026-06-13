"""Unit tests for tools.coordinator.tools.get_market_status."""

from __future__ import annotations

import asyncio
import zoneinfo
from datetime import datetime
from unittest.mock import patch


def _run(tz: str = "America/New_York") -> dict:
    from tools.coordinator.tools import get_market_status

    return asyncio.run(get_market_status(timezone=tz))


def _freeze(dt_str: str, tz_name: str):
    """Return a datetime object for the given local time string in tz_name."""
    tz = zoneinfo.ZoneInfo(tz_name)
    return datetime.fromisoformat(dt_str).replace(tzinfo=tz)


def test_market_open_during_hours():
    # Wednesday 10:00 ET — market open
    frozen = _freeze("2026-06-10 10:00:00", "America/New_York")
    with patch("tools.coordinator.tools.datetime") as mock_dt:
        mock_dt.now.return_value = frozen
        result = _run("America/New_York")
    assert result["is_open"] is True
    assert result["next_open"] is None
    assert result["next_close"] is not None


def test_market_closed_before_open():
    # Wednesday 8:00 ET — before open
    frozen = _freeze("2026-06-10 08:00:00", "America/New_York")
    with patch("tools.coordinator.tools.datetime") as mock_dt:
        mock_dt.now.return_value = frozen
        result = _run("America/New_York")
    assert result["is_open"] is False
    assert result["next_open"] is not None


def test_market_closed_after_close():
    # Wednesday 17:00 ET — after close
    frozen = _freeze("2026-06-10 17:00:00", "America/New_York")
    with patch("tools.coordinator.tools.datetime") as mock_dt:
        mock_dt.now.return_value = frozen
        result = _run("America/New_York")
    assert result["is_open"] is False


def test_market_closed_on_weekend():
    # Saturday 12:00 ET
    frozen = _freeze("2026-06-13 12:00:00", "America/New_York")
    with patch("tools.coordinator.tools.datetime") as mock_dt:
        mock_dt.now.return_value = frozen
        result = _run("America/New_York")
    assert result["is_open"] is False
    assert result["next_open"] is not None  # next Monday


def test_market_status_returns_all_fields():
    result = _run("America/New_York")
    for key in ("is_open", "next_open", "next_close", "timestamp", "timezone"):
        assert key in result
    assert result["timezone"] == "America/New_York"


def test_german_market_timezone():
    # Wednesday 10:00 Berlin — market open
    frozen = _freeze("2026-06-10 10:00:00", "Europe/Berlin")
    with patch("tools.coordinator.tools.datetime") as mock_dt:
        mock_dt.now.return_value = frozen
        result = _run("Europe/Berlin")
    assert result["is_open"] is True
    assert result["timezone"] == "Europe/Berlin"


def test_invalid_timezone_falls_back():
    # Should not raise — falls back to America/New_York
    result = _run("Not/A/Timezone")
    assert "is_open" in result
    assert result["timezone"] == "America/New_York"
