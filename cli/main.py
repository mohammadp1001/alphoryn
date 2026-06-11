"""
CLI entrypoint — `algotrade` command.

Usage:
  algotrade run                  # launch session wizard
  algotrade setup                # configure credentials
  algotrade history              # show recent sessions
"""
from __future__ import annotations

import asyncio
import json
import os

import typer
from dotenv import load_dotenv
from google.genai.types import Content, Part  # type: ignore[import]
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from agent.coordinator import build_app
from config import CONFIG_DIR, CONFIG_FILE, ETF_UNIVERSES, UNIVERSE_EXCHANGE_TZ
from db.schema import _connect, close_session, get_unresolved_trades, init_db, upsert_session
from infra.log_setup import configure_console_logging
from infra.observability import get_logger, setup_observability
from infra.secrets import get_alpaca_credentials
from models.enums import OperatingMode, SessionTimeframe
from models.session import SessionParams
from tools.execution.tools import get_portfolio

load_dotenv()

app = typer.Typer(name="algotrade", help="Autonomous ETF trading agent", no_args_is_help=True)
console = Console()


# ── Setup ─────────────────────────────────────────────────────────────────────

@app.command("setup")
def setup_cmd() -> None:
    """Configure API credentials and default settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    rprint(Panel("[bold]AlgoTrade Setup[/bold]", expand=False))
    rprint("This wizard stores credentials in your GCP Secret Manager.")
    rprint("You need GOOGLE_CLOUD_PROJECT set in your environment.\n")

    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or Prompt.ask("GCP Project ID")
    alpaca_key = Prompt.ask("Alpaca API key (paper trading)", password=True)
    _ = Prompt.ask("Alpaca API secret (paper trading)", password=True)

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
    mode: str = typer.Option(None, "--mode", "-m", help="SEMI_AUTO|FULL_AUTO"),
    loss_limit: float = typer.Option(None, "--loss-limit", help="Max loss in EUR"),
    timeframe: str = typer.Option(None, "--timeframe", "-t", help="Session duration: 30Min|1Hour|3Hour|12Hour|1Day|2Day|5Day"),
    shortlist_n: int = typer.Option(None, "--shortlist-n", help="Candidate shortlist size (1-5)"),
    hitl_timeout: int = typer.Option(None, "--hitl-timeout", help="HITL prompt timeout seconds"),
    universe: str = typer.Option(None, "--universe", "-u", help="US_SECTOR_ETFS|US_TECH_ETFS|US_BROAD_MARKET|COMMODITIES|FIXED_INCOME|INTERNATIONAL_DEVELOPED|EMERGING_MARKETS|DIVIDEND|HEALTHCARE|ENERGY|REAL_ESTATE|EU_MARKET|GERMAN_MARKET|CRYPTO|MIXED_MARKET"),
    allow_closed_market: bool = typer.Option(False, "--allow-closed-market", help="Proceed even when market is closed (useful for testing)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print session params, don't execute"),
) -> None:
    """Launch a trading session (interactive wizard fills missing params)."""
    rprint(Panel("[bold cyan]AlgoTrade Session[/bold cyan]", expand=False))

    # ── Wizard: fill in any missing params ───────────────────────────────────
    if not mode:
        mode = Prompt.ask(
            "Operating mode",
            choices=["SEMI_AUTO", "FULL_AUTO"],
            default="SEMI_AUTO",
        )

    if loss_limit is None:
        loss_limit = float(Prompt.ask("Loss limit (EUR)", default="500"))

    _tf_choices = [tf.value for tf in SessionTimeframe]
    if timeframe is None:
        timeframe = Prompt.ask(
            "Session duration",
            choices=_tf_choices,
            default=SessionTimeframe.DAY_1.value,
        )

    if shortlist_n is None:
        shortlist_n = IntPrompt.ask("Candidate shortlist size (1-5)", default=2)

    if hitl_timeout is None and mode == "SEMI_AUTO":
        hitl_timeout = IntPrompt.ask("HITL confirmation timeout (seconds)", default=60)
    elif hitl_timeout is None:
        hitl_timeout = 60

    if not universe:
        universe_choices = list(ETF_UNIVERSES.keys())
        universe = Prompt.ask(
            "Market universe",
            choices=universe_choices,
            default="US_SECTOR_ETFS",
        )

    params = SessionParams(
        timeframe=SessionTimeframe(timeframe),
        mode=OperatingMode(mode),
        loss_limit_eur=loss_limit,
        shortlist_n=shortlist_n,
        hitl_timeout_seconds=hitl_timeout,
        hitl_timeout_action="abort",
        universe=universe,
        allow_closed_market=allow_closed_market,
    )

    _print_session_params(params)

    if dry_run:
        rprint("[yellow]Dry run — session not started.[/yellow]")
        return

    if not yes and not Confirm.ask("\nStart session?", default=True):
        rprint("[yellow]Cancelled.[/yellow]")
        return

    asyncio.run(_run_session(params))


async def _run_session(params: SessionParams) -> None:
    configure_console_logging()

    init_db()

    runner, session_id, plan_state, session_service = build_app(params)
    setup_observability(session_id)

    upsert_session(
        session_id=session_id,
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

        portfolio_data = await get_portfolio()
        rprint(
            f"[dim]Loaded existing portfolio: "
            f"{len(portfolio_data['positions'])} position(s), "
            f"${portfolio_data['portfolio_value']:,.2f} value[/dim]"
        )
    except Exception as exc:
        rprint(f"[yellow]Could not load portfolio: {exc}[/yellow]")

    # ── Main session loop ─────────────────────────────────────────────────────
    universe_symbols = ETF_UNIVERSES.get(params.universe, ETF_UNIVERSES["US_SECTOR_ETFS"])
    exchange_tz = UNIVERSE_EXCHANGE_TZ.get(params.universe, "America/New_York")
    initial_message = (
        f"Start trading session {session_id}. "
        f"Mode: {params.mode.value}. "
        f"Loss limit: {params.loss_limit_eur} EUR. "
        f"Market universe: {params.universe} — symbols: {', '.join(universe_symbols)}. "
        f"Exchange timezone: {exchange_tz}. "
        f"When calling get_market_status, pass timezone='{exchange_tz}'. "
        f"Only consider symbols from this universe throughout the session. "
        f"Execute the decision cycle flow as per your instructions."
    )

    _outcome = "completed"
    try:
        content = Content(role="user", parts=[Part(text=initial_message)])
        async for event in runner.run_async(
            user_id="user",
            session_id=session_id,
            new_message=content,
        ):
            if not event.content or not event.content.parts:
                continue
            author = getattr(event, "author", None) or "agent"
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    rprint(f"\n[bold cyan][{author}][/bold cyan] {part.text}")
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    args_preview = ", ".join(f"{k}={v!r}" for k, v in (fc.args or {}).items())
                    rprint(f"[dim yellow]  -> [{author}] {fc.name}({args_preview})[/dim yellow]")
                elif hasattr(part, "function_response") and part.function_response:
                    fr = part.function_response
                    resp = fr.response or {}
                    summary = _summarise_tool_response(fr.name, resp)
                    rprint(f"[dim green]  <- [{author}] {fr.name}: {summary}[/dim green]")

    except KeyboardInterrupt:
        _outcome = "interrupted"
        rprint("\n[yellow]Session interrupted by user.[/yellow]")
    except Exception as exc:
        _outcome = "error"
        rprint(f"[red]Session error: {exc}[/red]")
        logger.error("session_error", extra={"trading_session_id": session_id, "error": str(exc)})
        raise
    finally:
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_API_SECRET", None)
        try:
            with _connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS cycle_count, "
                    "COALESCE(SUM(realised_pnl_pct), 0.0) AS total_pnl "
                    "FROM cycle_records WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            close_session(
                session_id,
                outcome=_outcome,
                realised_pnl=float(row["total_pnl"] or 0.0),
                cycle_count=int(row["cycle_count"] or 0),
            )
        except Exception:
            pass
        rprint(f"\n[bold]Session {session_id} ended.[/bold]")


async def _load_alpaca_credentials() -> tuple[str, str]:
    """Load Alpaca credentials from GCP Secret Manager or local env fallback."""
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")
    if key and secret:
        return key, secret

    return await get_alpaca_credentials()


# ── History ───────────────────────────────────────────────────────────────────

@app.command("history")
def history_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of sessions to show"),
) -> None:
    """Show recent trading session history."""
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

def _summarise_tool_response(tool_name: str, resp: dict) -> str:
    """Return a compact human-readable summary of a tool response for CLI display."""
    import json as _json

    if not resp:
        return "(empty)"

    if tool_name == "get_ohlcv" and "bars" in resp:
        bars = resp["bars"]
        if bars:
            last = bars[-1]
            return f"{resp.get('symbol')} | {len(bars)} bars | last close={last.get('close')}"
        return f"{resp.get('symbol')} | 0 bars"

    if tool_name == "screen_etfs" and "results" in resp:
        results = resp["results"]
        syms = [r["symbol"] for r in results]
        return f"{len(results)} ETFs passed: {', '.join(syms)}"

    if tool_name in ("score_technical", "score_momentum") and "symbol" in resp:
        return (
            f"{resp['symbol']} | score={resp.get('score')} "
            f"signal={resp.get('signal')} regime_fit={resp.get('regime_fit')}"
        )

    if tool_name == "detect_market_regime" and "regime" in resp:
        return (
            f"regime={resp['regime']} vix={resp.get('vix')} "
            f"{resp.get('benchmark_symbol', 'benchmark')}_20d={resp.get('benchmark_return_20d')}"
        )

    if tool_name == "get_macro_data":
        return f"vix={resp.get('vix')} yield_10y={resp.get('yield_10y')} dxy={resp.get('dxy')}"

    if tool_name == "get_quote" and "symbol" in resp:
        return f"{resp['symbol']} bid={resp.get('bid')} ask={resp.get('ask')}"

    if tool_name == "get_calibration":
        return (
            f"opt_win_rate={resp.get('opt_win_rate'):.0%} "
            f"pess_win_rate={resp.get('pess_win_rate'):.0%} "
            f"n={resp.get('trade_count')}"
        ) if resp.get("has_data") else "no calibration data yet"

    if tool_name == "get_portfolio":
        return (
            f"{len(resp.get('positions', []))} positions | "
            f"value=${resp.get('portfolio_value', 0):,.0f} | "
            f"cash=${resp.get('cash_usd', 0):,.0f}"
        )

    if tool_name in ("write_trade", "record_cycle"):
        return _json.dumps({k: v for k, v in resp.items() if k in ("trade_id", "written", "cycle_index", "outcome")})

    parts = []
    for k, v in resp.items():
        if isinstance(v, (str, int, float, bool)) and len(parts) < 6:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts) if parts else "(ok)"


def _print_session_params(params: SessionParams) -> None:
    table = Table(title="Session Parameters", show_header=False)
    table.add_column("", style="bold")
    table.add_column("")

    rows = [
        ("Mode", params.mode.value),
        ("Universe", params.universe),
        ("Loss limit", f"€{params.loss_limit_eur:,.0f}"),
        ("Timeframe", params.timeframe.value),
        ("Shortlist N", str(params.shortlist_n)),
        ("HITL timeout", f"{params.hitl_timeout_seconds}s ({params.hitl_timeout_action} on timeout)"),
        ("Allow closed market", str(params.allow_closed_market)),
    ]
    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


if __name__ == "__main__":
    app()
