"""Scheduler: candle boundary alignment, market hours check, and session loop.

T016 implements: startup candle boundary alignment + market hours check.
T029/T030 will expand run() with the full per-session loop.
"""

import math
import os
import time
from datetime import datetime, timedelta, timezone

import typer

from alphoryn.config.models import AlphorynConfig, _parse_duration_seconds
from alphoryn.memory.bank import MemoryBank

_TIMEFRAME_SECONDS: dict[str, int] = {"30min": 1800, "1H": 3600, "4H": 14400}


class Scheduler:
    """Drives the candle-by-candle session loop.

    At startup: aligns to the next candle close, prints a countdown to stdout,
    and waits. The full per-session loop is expanded in T029/T030.
    """

    def __init__(self, cfg: AlphorynConfig, bank: MemoryBank) -> None:
        self._cfg = cfg
        self._bank = bank

    # ------------------------------------------------------------------
    # Market clock
    # ------------------------------------------------------------------

    def get_market_clock(self) -> object:
        """Return the Alpaca market clock.

        Returns an object with attributes:
          - is_open (bool)
          - next_open (datetime, UTC-aware)
          - next_close (datetime, UTC-aware)
          - timestamp (datetime, UTC-aware)

        Raises:
            RuntimeError: if credentials are missing or the API call fails.
        """
        from alpaca.trading.client import TradingClient  # noqa: PLC0415

        client = TradingClient(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
            paper=True,
        )
        return client.get_clock()

    # ------------------------------------------------------------------
    # Candle boundary computation
    # ------------------------------------------------------------------

    def compute_next_candle_close(self, now: datetime) -> datetime:
        """Return the next UTC-aligned candle close boundary after *now*.

        Candles are aligned to the Unix epoch in UTC. For 1H candles the
        boundaries are :00 every hour; for 30min they are :00 and :30;
        for 4H they are 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.

        The returned datetime is always strictly after *now*.
        """
        period_secs = _TIMEFRAME_SECONDS[self._cfg.candle_timeframe]
        ts = now.timestamp()
        next_ts = math.ceil(ts / period_secs) * period_secs
        # If ceil gives the same second (ts was exactly on boundary), add one period
        if next_ts <= ts:
            next_ts += period_secs
        return datetime.fromtimestamp(next_ts, tz=timezone.utc)

    # ------------------------------------------------------------------
    # Market-open awareness
    # ------------------------------------------------------------------

    def next_market_open_close(self) -> tuple[datetime | None, datetime | None]:
        """Return (next_open, next_close) from Alpaca, or (None, None) on failure.

        Never raises — if the Alpaca API call fails the scheduler proceeds
        without a market-open guard (Principle IV: fail loud, hold safe —
        the warning is emitted to stderr).
        """
        try:
            clock = self.get_market_clock()
            next_open = getattr(clock, "next_open", None)
            next_close = getattr(clock, "next_close", None)
            return next_open, next_close
        except Exception as exc:
            typer.echo(
                f"WARN: Could not fetch market clock from Alpaca: {exc}. "
                "Proceeding without market-open guard.",
                err=True,
            )
            return None, None

    def is_market_open(self) -> bool:
        """Return True if the US equity market is currently open.

        Falls back to True (optimistic) if the Alpaca API is unavailable.
        """
        try:
            clock = self.get_market_clock()
            return bool(getattr(clock, "is_open", True))
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Countdown display and wait
    # ------------------------------------------------------------------

    def wait_for_candle_close(self, target: datetime, *, _sleep: object = None) -> None:
        """Print a countdown line and sleep until *target*.

        Args:
            target:  The UTC datetime to wait until.
            _sleep:  Injectable sleep callable (default: time.sleep).
                     Injected in tests to avoid real sleeps.

        Emits a WARN to stderr if the wait exceeds max_startup_latency_seconds.
        """
        _do_sleep = _sleep if _sleep is not None else time.sleep

        now = datetime.now(timezone.utc)
        wait_secs = (target - now).total_seconds()

        if wait_secs > self._cfg.max_startup_latency_seconds:
            typer.echo(
                f"WARN: {wait_secs:.0f}s wait to next candle exceeds "
                f"max_startup_latency_seconds={self._cfg.max_startup_latency_seconds}. "
                "Proceeding.",
                err=True,
            )

        close_str = target.strftime("%Y-%m-%d %H:%M UTC")
        remaining = max(0.0, wait_secs)
        mins, secs_part = divmod(int(remaining), 60)
        typer.echo(
            f"Waiting for next candle close at {close_str}"
            f" ({mins} min {secs_part:02d} sec)"
        )

        while True:
            now = datetime.now(timezone.utc)
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                break
            _do_sleep(min(10.0, remaining))

    # ------------------------------------------------------------------
    # Entry point (expanded in T029/T030)
    # ------------------------------------------------------------------

    def run(self, *, _sleep: object = None) -> None:
        """Start the scheduler.

        Phase 1 (T016): align to the next candle close and wait.
        The per-session loop and session budget enforcement are added in T029/T030.
        """
        now = datetime.now(timezone.utc)
        next_close = self.compute_next_candle_close(now)
        self.wait_for_candle_close(next_close, _sleep=_sleep)
