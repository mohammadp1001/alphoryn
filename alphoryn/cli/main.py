"""CLI entry point for Alphoryn.

Commands:
  run     — start a paper trading session
  status  — show current run state and open positions
  history — show session history from the memory bank
"""

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from alphoryn.config.loader import load_config
from alphoryn.config.models import AlphorynConfig
from alphoryn.memory.bank import MemoryBank, MemoryBankError
from alphoryn.secrets.client import SecretsError, load_alpaca_credentials

_VERSION = "0.0.1"

app = typer.Typer(add_completion=False, no_args_is_help=True)


# ---------------------------------------------------------------------------
# alphoryn run
# ---------------------------------------------------------------------------


@app.command()
def run(
    config: Annotated[
        str, typer.Option(help="Path to JSON config file.")
    ] = "config.json",
    etf1: Annotated[str | None, typer.Option(help="ETF 1 ticker. Overrides config.")] = None,
    etf2: Annotated[str | None, typer.Option(help="ETF 2 ticker. Overrides config.")] = None,
    exchange: Annotated[
        str | None, typer.Option(help="Exchange (informational). Overrides config.")
    ] = None,
    timeframe: Annotated[
        str | None,
        typer.Option(help="Candle timeframe: 30min | 1H | 4H. Overrides config."),
    ] = None,
    duration: Annotated[
        str | None, typer.Option(help="Run duration, e.g. 24H. Overrides config.")
    ] = None,
    budget: Annotated[
        float | None, typer.Option(help="Session money budget in USD. Overrides config.")
    ] = None,
    stop_loss: Annotated[
        float | None, typer.Option(help="Stop-loss percentage (0–1). Overrides config.")
    ] = None,
) -> None:
    """Start a paper trading session."""
    # 1. Load and validate config (exit 1 on failure)
    overrides: dict = {}
    if etf1 is not None:
        overrides["etf1"] = etf1
    if etf2 is not None:
        overrides["etf2"] = etf2
    if exchange is not None:
        overrides["exchange"] = exchange
    if timeframe is not None:
        overrides["candle_timeframe"] = timeframe
    if duration is not None:
        overrides["run_duration"] = duration
    if budget is not None:
        overrides["session_money_budget"] = budget if budget > 0 else None
    if stop_loss is not None:
        overrides["stop_loss_pct"] = stop_loss

    try:
        cfg = load_config(config_path=config, overrides=overrides or None)
    except Exception as exc:
        typer.echo(f"Config error: {exc}", err=True)
        sys.exit(1)

    # 2. Fetch secrets from GCP Secret Manager (exit 3 on failure)
    try:
        load_alpaca_credentials()
    except SecretsError as exc:
        typer.echo(f"Secret Manager error: {exc}", err=True)
        sys.exit(3)

    # 3. Load memory bank (exit 2 on failure)
    db_path = str(Path(cfg.memory_db_path).expanduser())
    try:
        bank = MemoryBank(db_path)
        open_positions = bank.load_open_positions()
    except MemoryBankError as exc:
        typer.echo(f"Memory bank error: {exc}", err=True)
        sys.exit(2)

    # 4. Warn if run_duration is not evenly divisible by candle_timeframe
    _warn_fractional_sessions(cfg)

    # 5. Print startup banner
    typer.echo(f"Alphoryn v{_VERSION} — Paper Trading")
    typer.echo(
        f"ETFs: {cfg.etf1} / {cfg.etf2}"
        f" | Timeframe: {cfg.candle_timeframe}"
        f" | Duration: {cfg.run_duration}"
    )
    typer.echo(f"Sessions planned: {cfg.session_count}")
    typer.echo(
        f"Memory bank: {db_path}"
        f" — {len(open_positions)} open position{'s' if len(open_positions) != 1 else ''} loaded"
    )

    # 6. Delegate to scheduler (imported lazily to keep startup testable)
    _start_scheduler(cfg, bank)


def _warn_fractional_sessions(cfg: AlphorynConfig) -> None:
    """Emit a warning when session count is fractional (rounded down)."""
    from alphoryn.config.models import _parse_duration_seconds

    _TIMEFRAME_SECONDS = {"30min": 1800, "1H": 3600, "4H": 14400}
    run_secs = _parse_duration_seconds(cfg.run_duration)
    candle_secs = _TIMEFRAME_SECONDS[cfg.candle_timeframe]
    if run_secs % candle_secs != 0:
        typer.echo(
            f"WARN: {cfg.run_duration} is not evenly divisible by {cfg.candle_timeframe};"
            f" rounding down to {cfg.session_count} sessions.",
            err=True,
        )


def _start_scheduler(cfg: AlphorynConfig, bank: MemoryBank) -> None:
    """Import and run the scheduler. Separate function so tests can patch it."""
    from alphoryn.scheduler.scheduler import Scheduler  # noqa: PLC0415

    scheduler = Scheduler(cfg, bank)
    scheduler.run()


# ---------------------------------------------------------------------------
# alphoryn status
# ---------------------------------------------------------------------------


@app.command()
def status(
    db: Annotated[
        str, typer.Option(help="Memory bank path.")
    ] = "~/.alphoryn/memory.db",
) -> None:
    """Show the current run state and all open positions."""
    db_path = str(Path(db).expanduser())
    try:
        bank = MemoryBank(db_path)
    except MemoryBankError as exc:
        typer.echo(f"Memory bank error: {exc}", err=True)
        raise typer.Exit(2)

    from sqlalchemy.orm import Session as DBSession

    from alphoryn.memory.schema import Position, Run

    with DBSession(bank._engine) as s:
        latest_run = s.query(Run).order_by(Run.id.desc()).first()
        if latest_run is None:
            typer.echo("No runs found.")
            return
        open_positions = (
            s.query(Position)
            .filter(Position.status == "OPEN")
            .order_by(Position.entry_time.asc())
            .all()
        )
        run_sessions = latest_run.sessions
        completed = sum(1 for sess in run_sessions if sess.status == "COMPLETED")
        remaining = latest_run.session_count_planned - completed

    typer.echo(
        f"Current run: run-{latest_run.id}"
        f" (started {latest_run.started_at.strftime('%Y-%m-%d %H:%M UTC')})"
    )
    typer.echo(f"Sessions: {completed} completed, {remaining} remaining")
    typer.echo("")
    try:
        cfg_snap = json.loads(latest_run.config_snapshot or "{}")
        etf1_ticker = cfg_snap.get("etf1", "ETF1")
        etf2_ticker = cfg_snap.get("etf2", "ETF2")
    except (json.JSONDecodeError, AttributeError):
        etf1_ticker = "ETF1"
        etf2_ticker = "ETF2"

    pos_by_etf = {pos.etf: pos for pos in open_positions}

    typer.echo("Open positions:")
    for label, ticker in [("ETF1", etf1_ticker), ("ETF2", etf2_ticker)]:
        pos = pos_by_etf.get(ticker)
        if pos is None:
            typer.echo(f"  {label} {ticker}  (no open position)")
        else:
            typer.echo(
                f"  {label} {ticker}  {pos.strategy}  {pos.direction}"
                f" @ {pos.entry_price:.2f}"
                f"  Stop: {pos.stop_loss_price:.2f}"
                f"  Status: {pos.status}"
            )


# ---------------------------------------------------------------------------
# alphoryn history
# ---------------------------------------------------------------------------


@app.command()
def history(
    run: Annotated[
        int | None, typer.Option(help="Filter by run number. Default: latest run.")
    ] = None,
    db: Annotated[
        str, typer.Option(help="Memory bank path.")
    ] = "~/.alphoryn/memory.db",
) -> None:
    """Show session history from the memory bank."""
    db_path = str(Path(db).expanduser())
    try:
        bank = MemoryBank(db_path)
    except MemoryBankError as exc:
        typer.echo(f"Memory bank error: {exc}", err=True)
        raise typer.Exit(2)

    from sqlalchemy.orm import Session as DBSession

    from alphoryn.memory.schema import Run
    from alphoryn.memory.schema import Session as SessionModel

    with DBSession(bank._engine) as s:
        if run is not None:
            target_run = s.query(Run).filter(Run.id == run).first()
        else:
            target_run = s.query(Run).order_by(Run.id.desc()).first()

        if target_run is None:
            typer.echo("No runs found.")
            return

        sessions = (
            s.query(SessionModel)
            .filter(SessionModel.run_id == target_run.id)
            .order_by(SessionModel.candle_close_at.desc())
            .all()
        )

    header = f"{'Session':<25} {'Candle Close':<22} {'ETF1':<22} {'ETF2'}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for sess in sessions:
        etf1_col = _format_decision(sess.etf1_strategy, sess.etf1_decision, sess.etf1_execution_result)
        etf2_col = _format_decision(sess.etf2_strategy, sess.etf2_decision, sess.etf2_execution_result)
        close_str = sess.candle_close_at.strftime("%Y-%m-%d %H:%M")
        typer.echo(f"{sess.id:<25} {close_str:<22} {etf1_col:<22} {etf2_col}")


def _format_decision(strategy: str | None, decision: str | None, result: str | None) -> str:
    if not strategy or not decision:
        return "—"
    strategy_abbr = "MR" if strategy == "MEAN_REVERSION" else "MOM"
    if result == "EXECUTED":
        return f"{strategy_abbr} → {decision} (exec)"
    return f"{strategy_abbr} → {decision}"
