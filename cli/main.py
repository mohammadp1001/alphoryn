"""
CLI entrypoint — `algotrade` command.

Usage:
  algotrade run                      # launch session wizard
  algotrade run --strategy MOMENTUM  # skip strategy prompt
  algotrade setup                    # configure credentials
  algotrade history                  # show recent sessions
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

load_dotenv()

app = typer.Typer(name="algotrade", help="Autonomous ETF trading agent", no_args_is_help=True)
console = Console()


# ── Setup ─────────────────────────────────────────────────────────────────────

@app.command("setup")
def setup_cmd() -> None:
    """Configure API credentials and default settings."""
    from config import CONFIG_DIR, CONFIG_FILE

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    rprint(Panel("[bold]AlgoTrade Setup[/bold]", expand=False))
    rprint("This wizard stores credentials in your GCP Secret Manager.")
    rprint("You need GOOGLE_CLOUD_PROJECT set in your environment.\n")

    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or Prompt.ask("GCP Project ID")
    alpaca_key = Prompt.ask("Alpaca API key (paper trading)", password=True)
    alpaca_secret = Prompt.ask("Alpaca API secret (paper trading)", password=True)

    config = {
        "gcp_project": project,
        "alpaca_key_secret_id": "alpaca-api-key",
        "alpaca_secret_secret_id": "alpaca-api-secret",
        "default_strategy": "MOMENTUM",
        "default_mode": "SEMI_AUTO",
        "default_loss_limit_eur": 500.0,
    }

    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    rprint(f"\n[green]Config saved to {CONFIG_FILE}[/green]")
    rprint("\nTo store Alpaca credentials in Secret Manager, run:")
    rprint(
        f"  echo -n '{alpaca_key[:4]}...' | gcloud secrets create alpaca-api-key "
        f"--project={project} --data-file=-"
    )
    rprint(
        "  echo -n '<secret>' | gcloud secrets create alpaca-api-secret "
        f"--project={project} --data-file=-"
    )


# ── Run ───────────────────────────────────────────────────────────────────────

@app.command("run")
def run_cmd(
    strategy: str = typer.Option(None, "--strategy", "-s", help="MOMENTUM|MEAN_REVERSION|SECTOR_ROTATION"),
    mode: str = typer.Option(None, "--mode", "-m", help="SEMI_AUTO|FULL_AUTO"),
    loss_limit: float = typer.Option(None, "--loss-limit", help="Max loss in EUR"),
    timeframe: int = typer.Option(None, "--timeframe", "-t", help="Days lookback (1|3|5)"),
    shortlist_n: int = typer.Option(None, "--shortlist-n", help="Candidate shortlist size (1-5)"),
    hitl_timeout: int = typer.Option(None, "--hitl-timeout", help="HITL prompt timeout seconds"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print session params, don't execute"),
) -> None:
    """Launch a trading session (interactive wizard fills missing params)."""
    from models.enums import OperatingMode, Strategy
    from models.session import SessionParams

    rprint(Panel("[bold cyan]AlgoTrade Session[/bold cyan]", expand=False))

    # ── Wizard: fill in any missing params ───────────────────────────────────
    if not strategy:
        strategy = Prompt.ask(
            "Strategy",
            choices=["MOMENTUM", "MEAN_REVERSION", "SECTOR_ROTATION"],
            default="MOMENTUM",
        )

    if not mode:
        mode = Prompt.ask(
            "Operating mode",
            choices=["SEMI_AUTO", "FULL_AUTO"],
            default="SEMI_AUTO",
        )

    if loss_limit is None:
        loss_limit = float(Prompt.ask("Loss limit (EUR)", default="500"))

    if timeframe is None:
        timeframe = IntPrompt.ask("Timeframe days (1/3/5)", default=3)

    if shortlist_n is None:
        shortlist_n = IntPrompt.ask("Candidate shortlist size (1-5)", default=2)

    if hitl_timeout is None and mode == "SEMI_AUTO":
        hitl_timeout = IntPrompt.ask("HITL confirmation timeout (seconds)", default=60)
    elif hitl_timeout is None:
        hitl_timeout = 60

    params = SessionParams(
        timeframe_days=timeframe,
        strategy=Strategy(strategy),
        mode=OperatingMode(mode),
        loss_limit_eur=loss_limit,
        shortlist_n=shortlist_n,
        hitl_timeout_seconds=hitl_timeout,
        hitl_timeout_action="abort",
    )

    _print_session_params(params)

    if dry_run:
        rprint("[yellow]Dry run — session not started.[/yellow]")
        return

    if not Confirm.ask("\nStart session?", default=True):
        rprint("[yellow]Cancelled.[/yellow]")
        return

    asyncio.run(_run_session(params))


async def _run_session(params: "SessionParams") -> None:
    from agent.coordinator import build_app
    from db.schema import init_db
    from infra.observability import get_logger, setup_observability

    init_db()

    runner, session_id, plan_state, session_service = build_app(params)
    setup_observability(session_id)

    from db.schema import upsert_session
    upsert_session(
        session_id=session_id,
        strategy=params.strategy.value,
        mode=params.mode.value,
    )

    await session_service.create_session(
        app_name="alphoryn",
        user_id="user",
        session_id=session_id,
    )
    logger = get_logger("cli.run")

    rprint(f"\n[bold green]Session started[/bold green] — ID: [cyan]{session_id}[/cyan]")
    logger.info("session_start session_id=%s", session_id)

    # ── Load existing Alpaca portfolio ────────────────────────────────────────
    try:
        api_key, api_secret = await _load_alpaca_credentials()
        os.environ["ALPACA_API_KEY"] = api_key
        os.environ["ALPACA_API_SECRET"] = api_secret

        from tools.execution.tools import get_portfolio
        portfolio_data = await get_portfolio()
        rprint(
            f"[dim]Loaded existing portfolio: "
            f"{len(portfolio_data['positions'])} position(s), "
            f"${portfolio_data['portfolio_value']:,.2f} value[/dim]"
        )
    except Exception as exc:
        rprint(f"[yellow]Could not load portfolio: {exc}[/yellow]")

    # ── Main session loop ─────────────────────────────────────────────────────
    initial_message = (
        f"Start trading session {session_id}. "
        f"Strategy: {params.strategy.value}. "
        f"Mode: {params.mode.value}. "
        f"Loss limit: {params.loss_limit_eur} EUR. "
        f"Execute the decision cycle flow as per your instructions."
    )

    try:
        from google.adk.runners import Runner  # type: ignore[import]
        from google.genai.types import Content, Part  # type: ignore[import]

        content = Content(role="user", parts=[Part(text=initial_message)])
        async for event in runner.run_async(
            user_id="user",
            session_id=session_id,
            new_message=content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        rprint(f"[dim white]{part.text[:200]}[/dim white]")

    except KeyboardInterrupt:
        rprint("\n[yellow]Session interrupted by user.[/yellow]")
    except Exception as exc:
        rprint(f"[red]Session error: {exc}[/red]")
        logger.error("session_error", extra={"trading_session_id": session_id, "error": str(exc)})
        raise
    finally:
        # Clear credentials from environment
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_API_SECRET", None)
        rprint(f"\n[bold]Session {session_id} ended.[/bold]")


async def _load_alpaca_credentials() -> tuple[str, str]:
    """Load Alpaca credentials from GCP Secret Manager or local env fallback."""
    # Try env vars first (development/test override)
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")
    if key and secret:
        return key, secret

    # Try GCP Secret Manager
    from infra.secrets import get_alpaca_credentials
    return await get_alpaca_credentials()


# ── History ───────────────────────────────────────────────────────────────────

@app.command("history")
def history_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of sessions to show"),
) -> None:
    """Show recent trading session history."""
    from db.schema import _connect, init_db

    init_db()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, started_at, closed_at, strategy, mode, outcome,
                   realised_pnl, cycle_count
            FROM sessions ORDER BY started_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        rprint("[yellow]No sessions found.[/yellow]")
        return

    table = Table(title="Recent Sessions", show_lines=True)
    table.add_column("ID", style="cyan", max_width=12)
    table.add_column("Started", style="dim")
    table.add_column("Strategy")
    table.add_column("Mode")
    table.add_column("Outcome")
    table.add_column("P&L (EUR)", justify="right")
    table.add_column("Cycles", justify="right")

    for row in rows:
        pnl = row["realised_pnl"] or 0.0
        pnl_style = "green" if pnl >= 0 else "red"
        table.add_row(
            row["id"][:8] + "…",
            (row["started_at"] or "")[:16],
            row["strategy"] or "—",
            row["mode"] or "—",
            row["outcome"] or "running",
            f"[{pnl_style}]{pnl:+.2f}[/{pnl_style}]",
            str(row["cycle_count"] or 0),
        )

    console.print(table)


# ── Status ────────────────────────────────────────────────────────────────────

@app.command("status")
def status_cmd() -> None:
    """Show calibration stats and unresolved trades."""
    from db.schema import _connect, get_unresolved_trades, init_db

    init_db()

    unresolved = get_unresolved_trades()
    if unresolved:
        rprint(f"[yellow]{len(unresolved)} unresolved trade(s) pending outcome resolution[/yellow]")
        for t in unresolved:
            rprint(f"  • {t.symbol} | order={t.order_id[:8]}… | opened={t.executed_at}")
    else:
        rprint("[green]No unresolved trades.[/green]")

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT agent, market_regime, strategy, wins, losses, ties
            FROM agent_pairwise ORDER BY agent, market_regime, strategy
            """
        ).fetchall()

    if rows:
        table = Table(title="Agent Calibration", show_lines=True)
        for col in ["Agent", "Regime", "Strategy", "Wins", "Losses", "Ties", "Win Rate"]:
            table.add_column(col)
        for r in rows:
            total = r["wins"] + r["losses"]
            wr = f"{r['wins']/total:.0%}" if total > 0 else "—"
            table.add_row(
                r["agent"], r["market_regime"], r["strategy"],
                str(r["wins"]), str(r["losses"]), str(r["ties"]), wr,
            )
        console.print(table)
    else:
        rprint("[dim]No calibration data yet.[/dim]")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_session_params(params: "SessionParams") -> None:
    table = Table(title="Session Parameters", show_header=False)
    table.add_column("", style="bold")
    table.add_column("")

    rows = [
        ("Strategy", params.strategy.value),
        ("Mode", params.mode.value),
        ("Loss limit", f"€{params.loss_limit_eur:,.0f}"),
        ("Timeframe", f"{params.timeframe_days} days"),
        ("Shortlist N", str(params.shortlist_n)),
        ("HITL timeout", f"{params.hitl_timeout_seconds}s ({params.hitl_timeout_action} on timeout)"),
    ]
    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


if __name__ == "__main__":
    app()
