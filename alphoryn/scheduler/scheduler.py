"""Scheduler: candle boundary alignment, market hours check, and session loop.

T016 implements startup candle boundary alignment + market hours check.
T029 adds session budget timers (87%/13% of candle timeframe) and heartbeat.
T030 adds the full per-session loop (main_agent → execution_agent → report → bank writes).
"""

import concurrent.futures
import json
import logging
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import typer
from alpaca.trading.client import TradingClient

from alphoryn.agents.feedback_agent import FeedbackAgent, FeedbackInput
from alphoryn.agents.main_agent import MainAgent, MainAgentError
from alphoryn.config.models import TIMEFRAME_SECONDS, AlphorynConfig
from alphoryn.execution.agent import AssetDecision, ExecutionAgent, SessionDecision
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import MemoryEntry, Position, Session, from_db_utc
from alphoryn.monitor.monitor import PositionMonitor
from alphoryn.reports.generator import ReportGenerator
from alphoryn.telemetry.logger import TelemetryLogger

_logger = logging.getLogger(__name__)

_INVESTIGATION_BUDGET_FRACTION = 0.87
_EXECUTE_BUDGET_FRACTION = 0.13
_HEARTBEAT_INTERVAL_SECS = 5 * 60


@dataclass(frozen=True)
class SessionSkip:
    """Why a session was not completed: the status, and the cause behind it.

    The two travel together because separating them is how the memory bank
    started lying. On 2026-08-13 two sessions failed - one on an unparseable
    model reply, one on a Vertex 429 - and both were filed as
    ``SKIPPED_DATA_UNAVAILABLE``. Market data was fine in both cases, and the
    exception text existed only on stdout, so the bank sent you to check Alpaca
    for a problem that was never there.

    *detail* is the exception text. It is persisted to the session's warnings so
    a post-mortem can read the real cause out of the bank alone.
    """

    status: str
    detail: str | None = None


class Scheduler:
    """Drives the candle-by-candle session loop.

    At startup: aligns to the next candle close, prints a countdown to stdout.
    Full session loop (T030): main_agent → execution_agent → HTML report → bank writes.
    Budget enforcement (T029): 87% of candle for investigation, 13% for execute; heartbeat.
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
        monitor: "PositionMonitor | None" = None,
        monitor_stop_event: "threading.Event | None" = None,
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
        self._monitor = monitor
        self._monitor_stop_event = monitor_stop_event
        candle_secs = TIMEFRAME_SECONDS[cfg.candle_timeframe]
        self._investigation_budget = (
            _investigation_budget_secs
            if _investigation_budget_secs is not None
            else int(candle_secs * _INVESTIGATION_BUDGET_FRACTION)
        )
        self._execute_budget = (
            _execute_budget_secs
            if _execute_budget_secs is not None
            else int(candle_secs * _EXECUTE_BUDGET_FRACTION)
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
        period_secs = TIMEFRAME_SECONDS[self._cfg.candle_timeframe]
        ts = now.timestamp()
        next_ts = math.ceil(ts / period_secs) * period_secs
        # If ceil gives the same second (ts was exactly on boundary), add one period
        if next_ts <= ts:
            next_ts += period_secs
        return datetime.fromtimestamp(next_ts, tz=UTC)

    # ------------------------------------------------------------------
    # Market-open awareness
    # ------------------------------------------------------------------

    def is_market_open(self) -> bool:
        """Return True if the US equity market is currently open.

        When cfg.extended_hours is True the market-open guard is bypassed so
        the scheduler can run during pre/post-market hours and for integration
        testing (constitution Development Standards).

        Falls back to False if the Alpaca clock is unavailable or malformed
        (Principle IV: fail loud, hold safe). An unreachable clock is not
        evidence that the market is open, and trading on that assumption is
        the one failure mode the guard exists to prevent — so the session is
        held and the reason is written to stderr.
        """
        if self._cfg.extended_hours:
            return True
        try:
            clock = self.get_market_clock()
        except Exception as exc:
            typer.echo(
                f"WARN: Could not fetch market clock from Alpaca: {exc}. "
                "Holding — treating the market as closed.",
                err=True,
            )
            return False
        is_open = getattr(clock, "is_open", None)
        if is_open is None:
            typer.echo(
                "WARN: Alpaca clock has no is_open field. "
                "Holding — treating the market as closed.",
                err=True,
            )
            return False
        return bool(is_open)

    # ------------------------------------------------------------------
    # Countdown display and wait
    # ------------------------------------------------------------------

    def wait_for_candle_close(self, target: datetime, *, _sleep: object = None) -> None:
        """Print a live countdown bar and sleep until *target*.

        Args:
            target:  The UTC datetime to wait until.
            _sleep:  Injectable sleep callable (default: time.sleep).
                     Injected in tests to avoid real sleeps.
        """
        _do_sleep = _sleep if _sleep is not None else time.sleep

        now = datetime.now(UTC)
        total_secs = max(0.0, (target - now).total_seconds())

        close_str = target.strftime("%Y-%m-%d %H:%M UTC")
        bar_width = 30
        enc = getattr(sys.stdout, "encoding", None) or ""
        _fill = "█" if "utf" in enc.lower() else "#"
        _empty = "░" if "utf" in enc.lower() else "-"

        while True:
            now = datetime.now(UTC)
            remaining = max(0.0, (target - now).total_seconds())
            elapsed = total_secs - remaining
            filled = int(bar_width * elapsed / total_secs) if total_secs > 0 else bar_width
            bar = _fill * filled + _empty * (bar_width - filled)
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

    def _recent_memory(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Return each ticker's recent memory entries, newest first (FR-008a).

        The investigation cannot account for prior evaluation outcomes unless
        they are put in front of it: the read-memory skill filters this list,
        and without it the whole learning loop was write-only.
        """
        return [
            {
                "ticker": entry.ticker,
                "strategy": entry.strategy,
                "session_id": entry.session_id,
                "decision": entry.decision,
                "outcome_judgment": entry.outcome_judgment,
                "regime_context": entry.regime_context,
                "created_at": entry.created_at.isoformat(),
            }
            for ticker in tickers
            for entry in self._bank.get_recent_memory_entries(ticker)
        ]

    def _run_investigation(
        self,
        session_id: str,
        candle_close_at: datetime,
        tickers: list[str],
    ) -> "tuple[SessionDecision | None, SessionSkip | None]":
        """Run main_agent.decide() with investigation budget and heartbeat.

        Returns ``(decision, skip)``. On success *skip* is None.

        A budget overrun yields ``SKIPPED_TIMEOUT``. A failure *inside the
        agent* - an unparseable reply, or no reply at all because the model
        provider refused - yields ``SKIPPED_AGENT_ERROR``. Only a failure
        reaching market data yields ``SKIPPED_DATA_UNAVAILABLE``.

        Those are three different problems with three different fixes, and
        filing one as another sends you to check Alpaca when the real story is
        the model. The same reasoning already separates ``SKIPPED_OVERRUN``
        (see ``_handle_overrun_candles``).

        All three leave ``decision`` as None. Emits BUDGET_TIMEOUT on timeout.
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
                    tickers,
                    candle_close_at,
                    self._recent_memory(tickers),
                    self._cfg.session_money_budget,
                )
                try:
                    return future.result(timeout=self._investigation_budget), None
                except concurrent.futures.TimeoutError:
                    if self._logger is not None:
                        self._logger.emit(
                            "BUDGET_TIMEOUT",
                            "scheduler",
                            {"phase": "investigation", "budget_secs": self._investigation_budget},
                            session_id=session_id,
                        )
                    return None, SessionSkip("SKIPPED_TIMEOUT")
                except MainAgentError as exc:
                    # The agent was reached and failed to produce a usable
                    # answer. Nothing to do with market data.
                    typer.echo(
                        f"[{session_id}] Investigation failed (agent): {exc}",
                        err=True,
                    )
                    return None, SessionSkip("SKIPPED_AGENT_ERROR", str(exc))
                except Exception as exc:
                    # Market data was unreachable. Skipping the session is
                    # correct; crashing the run is not.
                    typer.echo(
                        f"[{session_id}] Investigation failed: {exc}",
                        err=True,
                    )
                    return None, SessionSkip("SKIPPED_DATA_UNAVAILABLE", str(exc))
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=1.0)

    def _run_execute(self, decision: "SessionDecision") -> tuple[dict[str, str], str | None]:
        """Run execution_agent.execute() with execute budget.

        Returns ``(results, warning)`` where *results* maps ticker to its
        execution result. Emits BUDGET_TIMEOUT telemetry if the budget is
        exceeded, in which case *results* is empty and *warning* explains why.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self._execution_agent.execute,  # type: ignore[union-attr]
                decision,
            )
            try:
                return future.result(timeout=self._execute_budget), None
            except concurrent.futures.TimeoutError:
                if self._logger is not None:
                    self._logger.emit(
                        "BUDGET_TIMEOUT",
                        "scheduler",
                        {"phase": "execute", "budget_secs": self._execute_budget},
                    )
                return {}, f"Execution budget of {self._execute_budget}s exceeded."

    # ------------------------------------------------------------------
    # Full session loop (T030)
    # ------------------------------------------------------------------

    def _run_feedback(self, session_id: str) -> None:
        """Run feedback evaluation for positions whose window has closed.

        Called before investigation so the learning loop closes before new decisions.
        """
        if self._feedback_agent is None:
            return
        positions = self._bank.get_positions_due_for_feedback(datetime.now(UTC))
        for pos in positions:
            try:
                self._evaluate_position(pos, session_id)
            except Exception as exc:
                # One position that cannot be evaluated must not end the run
                # (FR-016a). The agent already retries and unblocks the ticker
                # itself; this only catches what escapes that.
                _logger.exception("Feedback evaluation failed for position %s", pos.id)
                typer.echo(
                    f"[{session_id}] FEEDBACK_ERROR {pos.ticker} - {exc}", err=True
                )
                if self._logger is not None:
                    self._logger.emit(
                        "EVALUATION_FAILED",
                        "scheduler",
                        {"position_id": pos.id, "error": str(exc)},
                        session_id=session_id,
                        etf=pos.ticker,
                    )

    def _evaluate_position(self, pos: Position, session_id: str) -> None:
        """Hand one closed position to the feedback agent."""
        entry_session = self._bank.get_session(pos.session_id)
        html_report_path = (
            entry_session.html_report_path if entry_session is not None else ""
        )
        feedback_input = FeedbackInput(
            position_id=pos.id,
            session_id=pos.session_id,
            ticker=pos.ticker,
            strategy=pos.strategy,
            html_report_path=html_report_path or "",
            entry_price=pos.entry_price,
            exit_price=pos.exit_price or pos.entry_price,
            exit_reason=pos.exit_reason or "UNKNOWN",
            evaluation_window_close_at=from_db_utc(pos.evaluation_window_close_at),
        )
        self._feedback_agent.evaluate(feedback_input, session_id)

    def _blocked_tickers(self, session_id: str) -> set[str]:
        """Return configured tickers that are feedback-blocked this session (FR-005)."""
        blocked = self._bank.get_feedback_blocked_tickers() & set(self._cfg.tickers)
        for ticker in sorted(blocked):
            typer.echo(f"[{session_id}] BLOCKED  {ticker} — prior position awaiting evaluation")
            if self._logger is not None:
                self._logger.emit(
                    "TICKER_BLOCKED",
                    "scheduler",
                    {"reason": "FEEDBACK_UNEVALUATED"},
                    session_id=session_id,
                    etf=ticker,
                )
        return blocked

    def _hold_decision(self, ticker: str, reasoning: str) -> "AssetDecision":
        """Build the Hold outcome recorded for a ticker that was not investigated."""
        return AssetDecision(
            ticker=ticker,
            action="HOLD",
            strategy=None,
            lot_size=None,
            exit_target=None,
            reasoning=reasoning,
        )

    def _merge_blocked_holds(
        self,
        decision: "SessionDecision",
        blocked: set[str],
    ) -> "tuple[SessionDecision, list[str]]":
        """Re-expand a decision over every configured ticker, in config order.

        The investigation only ever sees unblocked tickers, so blocked ones come
        back as Hold here — FR-005 requires their session outcome to be recorded
        even though no Investigation Agent call was made for them.

        Also returns the warnings this expansion uncovered: a ticker that was
        investigated but came back with no decision, and any ticker the agent
        invented. Both are recorded on the session per FR-011.
        """
        by_ticker = {d.ticker: d for d in decision.decisions}
        merged: list[AssetDecision] = []
        warnings: list[str] = []
        for ticker in self._cfg.tickers:
            investigated = by_ticker.pop(ticker, None)
            if investigated is not None:
                merged.append(investigated)
            elif ticker in blocked:
                merged.append(
                    self._hold_decision(
                        ticker, "Feedback-blocked: prior position awaiting evaluation (FR-005)."
                    )
                )
            else:
                merged.append(
                    self._hold_decision(ticker, "No decision returned by the investigation.")
                )
                warnings.append(f"{ticker}: investigated but no decision returned; recorded Hold.")
        for extra in by_ticker.values():  # tickers the agent invented; keep, do not drop
            merged.append(extra)
            warnings.append(f"{extra.ticker}: not a configured ticker, but the agent returned it.")
        return SessionDecision(session_id=decision.session_id, decisions=merged), warnings

    def _process_session(
        self,
        run_id: int,
        session_id: str,
        session_ordinal: int,
        candle_close_at: datetime,
    ) -> str:
        """Execute one complete feedback → investigation → decide → execute → report cycle."""
        candle_str = candle_close_at.strftime("%H:%M UTC")
        typer.echo(f"\n[{session_id}] SESSION START  candle={candle_str}")
        if self._logger is not None:
            self._logger.emit("SESSION_START", "scheduler", {}, session_id=session_id)

        self._run_feedback(session_id)

        t0 = datetime.now(UTC)
        warnings: list[str] = []
        blocked = self._blocked_tickers(session_id)
        active = [t for t in self._cfg.tickers if t not in blocked]
        warnings.extend(
            f"{ticker}: feedback-blocked; prior position awaiting evaluation (FR-005)."
            for ticker in sorted(blocked)
        )

        if active:
            typer.echo(f"[{session_id}] Investigating market snapshot …")
            decision, skip = self._run_investigation(session_id, candle_close_at, active)
        else:
            # FR-005: no Investigation Agent call is made when every ticker is blocked.
            typer.echo(f"[{session_id}] All tickers feedback-blocked — skipping investigation")
            decision, skip = SessionDecision(session_id=session_id, decisions=[]), None

        if decision is not None:
            decision, merge_warnings = self._merge_blocked_holds(decision, blocked)
            warnings.extend(merge_warnings)

        if skip is not None:
            typer.echo(f"[{session_id}] SKIPPED  {skip.status}")
            warnings.append(f"Session not completed: {skip.status}.")
            if skip.detail is not None:
                warnings.append(f"Cause: {skip.detail}")
        else:
            decision_str = "  |  ".join(
                f"{d.ticker}: {d.action} ({d.strategy})" for d in decision.decisions
            )
            typer.echo(f"[{session_id}] DECISION  {decision_str}")

        execution_results: dict[str, str] = {}
        if decision is not None and self._execution_agent is not None:
            typer.echo(f"[{session_id}] Executing …")
            execution_results, execute_warning = self._run_execute(decision)
            if execute_warning is not None:
                warnings.append(execute_warning)
            typer.echo(f"[{session_id}] Execution done")

        report_path: str | None = None
        if self._report_generator is not None and decision is not None:
            first = decision.decisions[0] if decision.decisions else None
            context: dict[str, Any] = {
                "session_id": session_id,
                "candle_close_at": candle_close_at.strftime("%Y-%m-%d %H:%M UTC"),
                "tickers": [d.ticker for d in decision.decisions],
                "ticker_details": [
                    {
                        "ticker": d.ticker,
                        "action": d.action,
                        "strategy": d.strategy,
                        "reasoning": d.reasoning,
                        "memory_summary": None,
                        "execution_result": execution_results.get(d.ticker),
                    }
                    for d in decision.decisions
                ],
                "strategy": first.strategy if first else None,
                "signals": None,
                "execution_result": None,
                "position": None,
            }
            report_path = self._report_generator.write(session_id, context)
            typer.echo(f"[{session_id}] Report -> {report_path}")

        ticker_decisions_json: str | None = None
        if decision is not None:
            ticker_decisions_json = json.dumps(
                {
                    d.ticker: {
                        "strategy": d.strategy,
                        "decision": d.action,
                        "execution_result": execution_results.get(d.ticker),
                    }
                    for d in decision.decisions
                }
            )

        session_status = skip.status if skip is not None else "COMPLETED"
        session_record = Session(
            id=session_id,
            run_id=run_id,
            candle_close_at=candle_close_at,
            created_at=datetime.now(UTC),
            status=session_status,
            html_report_path=report_path,
            ticker_decisions=ticker_decisions_json,
            warnings=json.dumps(warnings) if warnings else None,
        )
        self._bank.write_session(session_record)

        if decision is not None:
            for asset_decision in decision.decisions:
                if asset_decision.strategy is None:
                    continue  # no regime identified — nothing to persist in memory bank
                entry = MemoryEntry(
                    ticker=asset_decision.ticker,
                    strategy=asset_decision.strategy,
                    session_id=session_id,
                    decision=asset_decision.action,
                    regime_context=json.dumps({"session_ordinal": session_ordinal}),
                    created_at=datetime.now(UTC),
                )
                self._bank.write_memory_entry(entry)
            memory_str = "  ".join(f"{d.ticker}={d.action}" for d in decision.decisions)
            typer.echo(f"[{session_id}] Memory written  {memory_str}")

        if self._logger is not None:
            latency_ms = int((datetime.now(UTC) - t0).total_seconds() * 1000)
            self._logger.emit(
                "SESSION_END", "scheduler", {}, session_id=session_id, latency_ms=latency_ms
            )
        typer.echo(f"[{session_id}] SESSION END  status={session_status}")
        return session_status

    def _record_skipped_session(
        self,
        run_id: int,
        session_id: str,
        candle_close_at: datetime,
        status: str,
    ) -> None:
        """Persist a Session row for a candle the scheduler never processed.

        Used for market-closed candles and data fetch failures so history views
        and reporting have a contiguous session record.
        """
        session_record = Session(
            id=session_id,
            run_id=run_id,
            candle_close_at=candle_close_at,
            created_at=datetime.now(UTC),
            status=status,
            html_report_path=None,
            ticker_decisions=None,
            warnings=None,
        )
        self._bank.write_session(session_record)

    # ------------------------------------------------------------------
    # Position monitor lifecycle
    # ------------------------------------------------------------------

    def _start_monitor(self) -> None:
        """Start the position monitor thread before the first session."""
        if self._monitor is None:
            return
        self._monitor.start()
        typer.echo("Position monitor started.")
        if self._logger is not None:
            self._logger.emit("MONITOR_STARTED", "scheduler", {})

    def _drain_open_positions(self, *, _sleep: object = None) -> None:
        """Keep the monitor running past the last session until nothing is OPEN.

        Per contracts/agents.md the stop signal may only be set once no
        positions remain OPEN, so the process waits candle by candle until the
        monitor has closed everything. Each position carries its own window
        deadline, so nothing has to be published to the monitor here.
        """
        if self._monitor is None or not self._bank.load_open_positions():
            return
        typer.echo("Run complete - holding process open until all positions close ...")
        while self._bank.load_open_positions():
            next_close = self.compute_next_candle_close(datetime.now(UTC))
            self.wait_for_candle_close(next_close, _sleep=_sleep)

    def _stop_monitor(self) -> None:
        """Signal the monitor to stop and wait for the thread to exit."""
        if self._monitor is None:
            return
        if self._monitor_stop_event is not None:
            self._monitor_stop_event.set()
        self._monitor.join(timeout=5.0)
        typer.echo("Position monitor stopped.")
        if self._logger is not None:
            self._logger.emit("MONITOR_STOPPED", "scheduler", {})

    def _handle_overrun_candles(
        self,
        run_id: int,
        last_candle_close: datetime,
        next_close: datetime,
        session_ordinal: int,
    ) -> int:
        """Record skipped session rows for intermediate closed candles missed due to
        processing overrun (SC-003).

        An overrun candle is recorded as ``SKIPPED_OVERRUN``, not
        ``SKIPPED_DATA_UNAVAILABLE``: the market data was fine, the previous
        session was still running. Those are two different problems with two
        different fixes, and filing one as the other sends you to check Alpaca
        when the real story is that the session budget needs a look (issue #169).
        """
        candle_secs = TIMEFRAME_SECONDS[self._cfg.candle_timeframe]
        overrun_time = last_candle_close + timedelta(seconds=candle_secs)
        now = datetime.now(UTC)
        while overrun_time <= now and overrun_time < next_close:
            session_id = f"run-{run_id}/session-{session_ordinal:04d}"
            status = (
                "SKIPPED_MARKET_CLOSED" if not self.is_market_open() else "SKIPPED_OVERRUN"
            )
            self._record_skipped_session(run_id, session_id, overrun_time, status)
            session_ordinal += 1
            overrun_time += timedelta(seconds=candle_secs)
        return session_ordinal

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
            config_snapshot=json.dumps({"tickers": self._cfg.tickers}),
            session_count_planned=self._cfg.session_count,
        )

        sessions_completed = 0
        session_ordinal = 1
        self._start_monitor()

        try:
            while sessions_completed < self._cfg.session_count:
                candle_close_at = datetime.now(UTC)

                session_id = f"run-{run_id}/session-{session_ordinal:04d}"

                if not self.is_market_open():
                    typer.echo(f"[{session_id}] MARKET_CLOSED - waiting for next candle")
                    if self._logger is not None:
                        self._logger.emit(
                            "MARKET_CLOSED",
                            "scheduler",
                            {"session_ordinal": session_ordinal},
                            session_id=session_id,
                        )
                    self._record_skipped_session(
                        run_id, session_id, candle_close_at, "SKIPPED_MARKET_CLOSED"
                    )
                    next_close = self.compute_next_candle_close(datetime.now(UTC))
                    session_ordinal += 1
                    session_ordinal = self._handle_overrun_candles(
                        run_id, candle_close_at, next_close, session_ordinal
                    )
                    self.wait_for_candle_close(next_close, _sleep=_sleep)
                    continue  # skipped sessions not counted against total (FR-018)

                session_status = self._process_session(
                    run_id, session_id, session_ordinal, candle_close_at
                )

                if session_status == "COMPLETED":
                    sessions_completed += 1
                session_ordinal += 1

                next_close = self.compute_next_candle_close(datetime.now(UTC))
                session_ordinal = self._handle_overrun_candles(
                    run_id, candle_close_at, next_close, session_ordinal
                )
                self.wait_for_candle_close(next_close, _sleep=_sleep)
        finally:
            self._bank.end_run(run_id)
            self._drain_open_positions(_sleep=_sleep)
            self._stop_monitor()
