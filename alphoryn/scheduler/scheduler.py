"""Scheduler: candle boundary alignment, market hours check, and session loop.

T016 implements startup candle boundary alignment + market hours check.
T029 adds session budget timers (52-min investigation, 7-min execute) and heartbeat.
T030 adds the full per-session loop (main_agent → execution_agent → report → bank writes).
"""

import concurrent.futures
import json
import math
import os
import sys
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import typer

from alphoryn.config.models import AlphorynConfig
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import MemoryEntry, Session

if TYPE_CHECKING:
    from alphoryn.agents.feedback_agent import FeedbackAgent
    from alphoryn.agents.main_agent import MainAgent
    from alphoryn.execution.agent import ExecutionAgent, SessionDecision
    from alphoryn.reports.generator import ReportGenerator
    from alphoryn.telemetry.logger import TelemetryLogger

_TIMEFRAME_SECONDS: dict[str, int] = {"30min": 1800, "1H": 3600, "4H": 14400}
_INVESTIGATION_BUDGET_SECS = 52 * 60
_EXECUTE_BUDGET_SECS = 7 * 60
_HEARTBEAT_INTERVAL_SECS = 5 * 60


class Scheduler:
    """Drives the candle-by-candle session loop.

    At startup: aligns to the next candle close, prints a countdown to stdout.
    Full session loop (T030): main_agent → execution_agent → HTML report → bank writes.
    Budget enforcement (T029): 52-min investigation cap; 7-min execute cap; heartbeat.
    """

    def __init__(
        self,
        cfg: AlphorynConfig,
        bank: MemoryBank,
        *,
        main_agent: "MainAgent | None" = None,
        execution_agent: "ExecutionAgent | None" = None,
        feedback_agent: "FeedbackAgent | None" = None,
        report_generator: "ReportGenerator | None" = None,
        logger: "TelemetryLogger | None" = None,
        _investigation_budget_secs: int | None = None,
        _execute_budget_secs: int | None = None,
        _heartbeat_interval_secs: int | None = None,
    ) -> None:
        self._cfg = cfg
        self._bank = bank
        self._main_agent = main_agent
        self._execution_agent = execution_agent
        self._feedback_agent = feedback_agent
        self._report_generator = report_generator
        self._logger = logger
        self._investigation_budget = (
            _investigation_budget_secs
            if _investigation_budget_secs is not None
            else _INVESTIGATION_BUDGET_SECS
        )
        self._execute_budget = (
            _execute_budget_secs if _execute_budget_secs is not None else _EXECUTE_BUDGET_SECS
        )
        self._heartbeat_interval = (
            _heartbeat_interval_secs
            if _heartbeat_interval_secs is not None
            else _HEARTBEAT_INTERVAL_SECS
        )

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
        from alpaca.trading.client import TradingClient

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
        return datetime.fromtimestamp(next_ts, tz=UTC)

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
        """Print a live countdown bar and sleep until *target*.

        Args:
            target:  The UTC datetime to wait until.
            _sleep:  Injectable sleep callable (default: time.sleep).
                     Injected in tests to avoid real sleeps.

        Emits a WARN to stderr if the wait exceeds max_startup_latency_seconds.
        """
        _do_sleep = _sleep if _sleep is not None else time.sleep

        now = datetime.now(UTC)
        total_secs = max(0.0, (target - now).total_seconds())

        if total_secs > self._cfg.max_startup_latency_seconds:
            typer.echo(
                f"WARN: {total_secs:.0f}s wait to next candle exceeds "
                f"max_startup_latency_seconds={self._cfg.max_startup_latency_seconds}. "
                "Proceeding.",
                err=True,
            )

        close_str = target.strftime("%Y-%m-%d %H:%M UTC")
        bar_width = 30

        while True:
            now = datetime.now(UTC)
            remaining = max(0.0, (target - now).total_seconds())
            elapsed = total_secs - remaining
            filled = int(bar_width * elapsed / total_secs) if total_secs > 0 else bar_width
            bar = "█" * filled + "░" * (bar_width - filled)
            mins, secs_part = divmod(int(remaining), 60)
            sys.stdout.write(
                f"\rWaiting for next candle close at {close_str}"
                f"  [{bar}]  {mins:02d}:{secs_part:02d} remaining"
            )
            sys.stdout.flush()
            if remaining <= 0:
                break
            _do_sleep(min(1.0, remaining))

        sys.stdout.write("\n")
        sys.stdout.flush()

    # ------------------------------------------------------------------
    # Session budget helpers (T029)
    # ------------------------------------------------------------------

    def _heartbeat_loop(self, session_id: str, stop_event: threading.Event) -> None:
        """Print heartbeat lines every heartbeat_interval seconds."""
        t_start = time.time()
        while not stop_event.wait(self._heartbeat_interval):
            elapsed_min = int((time.time() - t_start) / 60)
            typer.echo(f"[{session_id}] investigating... {elapsed_min} min elapsed")

    def _run_investigation(
        self,
        session_id: str,
        candle_close_at: datetime,
    ) -> "SessionDecision | None":
        """Run main_agent.decide() with investigation budget and heartbeat.

        Returns the SessionDecision, or None if the budget was exceeded.
        Emits BUDGET_TIMEOUT telemetry on timeout.
        """
        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(session_id, stop_heartbeat),
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self._main_agent.decide,  # type: ignore[union-attr]
                    session_id,
                    self._cfg.etf1,
                    self._cfg.etf2,
                    candle_close_at,
                )
                try:
                    return future.result(timeout=self._investigation_budget)
                except concurrent.futures.TimeoutError:
                    if self._logger is not None:
                        self._logger.emit(
                            "BUDGET_TIMEOUT",
                            "scheduler",
                            {"phase": "investigation", "budget_secs": self._investigation_budget},
                            session_id=session_id,
                        )
                    return None
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=1.0)

    def _run_execute(self, decision: "SessionDecision") -> None:
        """Run execution_agent.execute() with execute budget.

        Emits BUDGET_TIMEOUT telemetry if the 7-min budget is exceeded.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self._execution_agent.execute,  # type: ignore[union-attr]
                decision,
            )
            try:
                future.result(timeout=self._execute_budget)
            except concurrent.futures.TimeoutError:
                if self._logger is not None:
                    self._logger.emit(
                        "BUDGET_TIMEOUT",
                        "scheduler",
                        {"phase": "execute", "budget_secs": self._execute_budget},
                    )

    # ------------------------------------------------------------------
    # Full session loop (T030)
    # ------------------------------------------------------------------

    def _run_feedback(self, session_id: str, session_ordinal: int) -> None:
        """Run feedback evaluation for positions due at this session ordinal.

        Called before investigation so the learning loop closes before new decisions.
        """
        if self._feedback_agent is None:
            return
        from alphoryn.agents.feedback_agent import FeedbackInput

        positions = self._bank.get_positions_due_for_feedback(session_ordinal)
        for pos in positions:
            entry_session = self._bank.get_session(pos.session_id)
            html_report_path = (
                entry_session.html_report_path
                if entry_session is not None
                else ""
            )
            feedback_input = FeedbackInput(
                position_id=pos.id,
                session_id=pos.session_id,
                etf=pos.etf,
                strategy=pos.strategy,
                html_report_path=html_report_path or "",
                entry_price=pos.entry_price,
                exit_price=pos.exit_price or pos.entry_price,
                exit_reason=pos.exit_reason or "UNKNOWN",
            )
            self._feedback_agent.evaluate(feedback_input, session_id)

    def _process_session(
        self,
        run_id: int,
        session_id: str,
        session_ordinal: int,
        candle_close_at: datetime,
    ) -> None:
        """Execute one complete feedback → investigation → decide → execute → report cycle."""
        if self._logger is not None:
            self._logger.emit("SESSION_START", "scheduler", {}, session_id=session_id)

        self._run_feedback(session_id, session_ordinal)

        t0 = datetime.now(UTC)
        decision = self._run_investigation(session_id, candle_close_at)

        if decision is not None and self._execution_agent is not None:
            self._run_execute(decision)

        report_path: str | None = None
        if self._report_generator is not None and decision is not None:
            context: dict[str, Any] = {
                "session_id": session_id,
                "strategy": decision.etf1.strategy,
                "etf1": decision.etf1.etf,
                "etf2": decision.etf2.etf,
                "etf1_action": decision.etf1.action,
                "etf2_action": decision.etf2.action,
            }
            report_path = self._report_generator.write(
                f"run-{run_id}", session_id, context
            )

        session_status = "COMPLETED" if decision is not None else "SKIPPED_TIMEOUT"
        session_record = Session(
            id=session_id,
            run_id=run_id,
            candle_close_at=candle_close_at,
            created_at=datetime.now(UTC),
            status=session_status,
            html_report_path=report_path,
            etf1_strategy=decision.etf1.strategy if decision else None,
            etf2_strategy=decision.etf2.strategy if decision else None,
            etf1_decision=decision.etf1.action if decision else "HOLD",
            etf2_decision=decision.etf2.action if decision else "HOLD",
        )
        self._bank.write_session(session_record)

        if decision is not None:
            for etf_decision in (decision.etf1, decision.etf2):
                entry = MemoryEntry(
                    etf=etf_decision.etf,
                    strategy=etf_decision.strategy,
                    session_id=session_id,
                    decision=etf_decision.action,
                    regime_context=json.dumps({"session_ordinal": session_ordinal}),
                    created_at=datetime.now(UTC),
                )
                self._bank.write_memory_entry(entry)

        if self._logger is not None:
            latency_ms = int((datetime.now(UTC) - t0).total_seconds() * 1000)
            self._logger.emit(
                "SESSION_END", "scheduler", {}, session_id=session_id, latency_ms=latency_ms
            )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, *, _sleep: object = None) -> None:
        """Start the scheduler.

        Aligns to the next candle close, then runs the full session loop if
        agents are configured. Without agents (startup-only mode), returns
        immediately after alignment (backward-compatible with T016).
        """
        now = datetime.now(UTC)
        next_close = self.compute_next_candle_close(now)
        self.wait_for_candle_close(next_close, _sleep=_sleep)

        if self._main_agent is None:
            return  # startup-only mode (T016 backward compatibility)

        run_id = self._bank.start_run(
            config_snapshot=json.dumps(
                {"etf1": self._cfg.etf1, "etf2": self._cfg.etf2}
            ),
            session_count_planned=self._cfg.session_count,
        )

        sessions_completed = 0
        session_ordinal = 1

        while sessions_completed < self._cfg.session_count:
            candle_close_at = datetime.now(UTC)

            if not self.is_market_open():
                if self._logger is not None:
                    self._logger.emit(
                        "MARKET_CLOSED",
                        "scheduler",
                        {"session_ordinal": session_ordinal},
                    )
                next_close = self.compute_next_candle_close(datetime.now(UTC))
                self.wait_for_candle_close(next_close, _sleep=_sleep)
                session_ordinal += 1
                continue  # skipped sessions not counted against total (FR-018)

            session_id = f"run-{run_id}/session-{session_ordinal:04d}"
            self._process_session(run_id, session_id, session_ordinal, candle_close_at)

            sessions_completed += 1
            session_ordinal += 1

            next_close = self.compute_next_candle_close(datetime.now(UTC))
            self.wait_for_candle_close(next_close, _sleep=_sleep)

        self._bank.end_run(run_id)
