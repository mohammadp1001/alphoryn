"""Unit tests for cli.main — Typer CLI commands."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "cli_test.db"
    monkeypatch.setattr("config.DB_PATH", db_file)

    @contextmanager
    def _connect(path=None):
        conn = sqlite3.connect(str(path or db_file), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr("db.schema._connect", _connect)
    from db.schema import init_db
    init_db(db_file)
    return db_file


@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".algotrade"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    monkeypatch.setattr("config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("config.CONFIG_FILE", config_file)
    return config_file


# ── setup_cmd ─────────────────────────────────────────────────────────────────

def test_setup_cmd_creates_config_file(tmp_config, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    # Simulate user inputs: key, secret
    result = runner.invoke(app, ["setup"], input="PK_test_key\nSK_test_secret\n")

    assert result.exit_code == 0
    assert tmp_config.exists()

    config = json.loads(tmp_config.read_text())
    assert config["gcp_project"] == "test-project"
    assert config["default_strategy"] == "MOMENTUM"


def test_setup_cmd_prompts_for_project_if_not_in_env(tmp_config, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    result = runner.invoke(app, ["setup"],
                           input="my-gcp-project\nPK_test_key\nSK_test_secret\n")

    assert result.exit_code == 0
    assert tmp_config.exists()
    config = json.loads(tmp_config.read_text())
    assert config["gcp_project"] == "my-gcp-project"


# ── run_cmd (dry_run) ─────────────────────────────────────────────────────────

def test_run_cmd_dry_run_does_not_start_session():
    result = runner.invoke(
        app,
        ["run", "--strategy", "MOMENTUM", "--mode", "SEMI_AUTO",
         "--loss-limit", "500", "--timeframe", "3", "--shortlist-n", "2",
         "--hitl-timeout", "60", "--universe", "US_SECTOR_ETFS", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output


def test_run_cmd_dry_run_all_strategies():
    for strategy in ["MOMENTUM", "MEAN_REVERSION", "SECTOR_ROTATION"]:
        result = runner.invoke(
            app,
            ["run", "--strategy", strategy, "--mode", "FULL_AUTO",
             "--loss-limit", "1000", "--timeframe", "1",
             "--shortlist-n", "1", "--hitl-timeout", "30",
             "--universe", "US_SECTOR_ETFS", "--dry-run"],
        )
        assert result.exit_code == 0, f"Strategy {strategy} failed: {result.output}"


def test_run_cmd_cancelled_by_user():
    """User says 'no' at confirm prompt — session should not start."""
    result = runner.invoke(
        app,
        ["run", "--strategy", "MOMENTUM", "--mode", "SEMI_AUTO",
         "--loss-limit", "500", "--timeframe", "3", "--shortlist-n", "2",
         "--hitl-timeout", "60", "--universe", "US_SECTOR_ETFS"],
        input="n\n",  # decline to start
    )
    assert result.exit_code == 0
    assert "Cancelled" in result.output or "cancel" in result.output.lower()


def test_run_cmd_wizard_fills_missing_params():
    """All params provided interactively."""
    result = runner.invoke(
        app,
        ["run", "--dry-run"],
        input="MOMENTUM\nSEMI_AUTO\n500\n3\n2\n60\nUS_SECTOR_ETFS\n",
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output


def test_run_cmd_full_auto_skips_hitl_prompt():
    """FULL_AUTO mode doesn't prompt for HITL timeout when given directly."""
    result = runner.invoke(
        app,
        ["run", "--strategy", "MOMENTUM", "--mode", "FULL_AUTO",
         "--loss-limit", "500", "--timeframe", "3", "--shortlist-n", "2",
         "--universe", "US_SECTOR_ETFS", "--dry-run"],
    )
    assert result.exit_code == 0


# ── history_cmd ───────────────────────────────────────────────────────────────

def test_history_cmd_empty_db(tmp_db):
    result = runner.invoke(app, ["history"])
    assert result.exit_code == 0
    assert "No sessions found" in result.output


def test_history_cmd_with_sessions(tmp_db):
    from db.schema import upsert_session, close_session
    upsert_session("sess-hist-1", "MOMENTUM", "SEMI_AUTO")
    close_session("sess-hist-1", "clean", 50.0, 3)

    result = runner.invoke(app, ["history"])
    assert result.exit_code == 0
    assert "sess-hist-1"[:8] in result.output or "MOMENTUM" in result.output


def test_history_cmd_limit_option(tmp_db):
    from db.schema import upsert_session
    for i in range(5):
        upsert_session(f"sess-lim-{i}", "MOMENTUM", "SEMI_AUTO")

    result = runner.invoke(app, ["history", "--limit", "2"])
    assert result.exit_code == 0


# ── status_cmd ────────────────────────────────────────────────────────────────

def test_status_cmd_no_unresolved_trades(tmp_db):
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No unresolved trades" in result.output


def test_status_cmd_with_calibration_data(tmp_db):
    # Insert some pairwise data
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO agent_pairwise (agent, market_regime, strategy, wins, losses, ties, last_updated)
        VALUES ('optimist', 'BULL_TREND', 'MOMENTUM', 5, 3, 1, '2025-01-01')
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "optimist" in result.output


# ── _load_alpaca_credentials ──────────────────────────────────────────────────

def test_load_alpaca_credentials_from_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "env-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "env-secret")

    from cli.main import _load_alpaca_credentials
    key, secret = asyncio.run(_load_alpaca_credentials())

    assert key == "env-key"
    assert secret == "env-secret"


def test_load_alpaca_credentials_from_secret_manager(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    with patch("infra.secrets.get_alpaca_credentials",
               new=AsyncMock(return_value=("sm-key", "sm-secret"))):
        from cli.main import _load_alpaca_credentials
        key, secret = asyncio.run(_load_alpaca_credentials())

    assert key == "sm-key"
    assert secret == "sm-secret"


# ── _print_session_params (helper) ───────────────────────────────────────────

def test_print_session_params_does_not_raise():
    from models.session import SessionParams
    from models.enums import Strategy, OperatingMode
    from cli.main import _print_session_params

    params = SessionParams(
        strategy=Strategy.MOMENTUM,
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe_days=3,
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )
    # Should not raise
    _print_session_params(params)


# ── _run_session integration ──────────────────────────────────────────────────

def test_run_session_clears_credentials_on_exception(tmp_db, monkeypatch):
    """Credentials must be cleared from env even if session errors."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.session import SessionParams
    from models.enums import Strategy, OperatingMode

    params = SessionParams(
        strategy=Strategy.MOMENTUM,
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe_days=3,
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )

    mock_runner = MagicMock()

    async def raise_exc(*args, **kwargs):
        raise RuntimeError("mock runner error")
        return
        yield  # make it an async generator

    mock_runner.run_async = raise_exc

    mock_session_service = AsyncMock()

    with patch("agent.coordinator.build_app",
               return_value=(mock_runner, "mock-session-id", MagicMock(), mock_session_service)):
        with patch("db.schema.init_db"):
            with patch("infra.observability.setup_observability"):
                with patch("tools.execution.tools.get_portfolio",
                           new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})):
                    from cli.main import _run_session
                    with pytest.raises(RuntimeError):
                        asyncio.run(_run_session(params))

    # Credentials must be cleared
    assert os.environ.get("ALPACA_API_KEY") is None
    assert os.environ.get("ALPACA_API_SECRET") is None


def test_run_session_portfolio_load_success(tmp_db, monkeypatch):
    """Lines 172-173: portfolio loaded successfully → rprint message."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.session import SessionParams
    from models.enums import Strategy, OperatingMode

    params = SessionParams(
        strategy=Strategy.MOMENTUM,
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe_days=3,
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )

    # runner.run_async yields one event then finishes
    mock_event = MagicMock()
    mock_part = MagicMock()
    mock_part.text = "Session complete."
    mock_event.content = MagicMock()
    mock_event.content.parts = [mock_part]

    async def fake_run_async(*args, **kwargs):
        yield mock_event

    mock_runner = MagicMock()
    mock_runner.run_async = fake_run_async

    mock_session_service = AsyncMock()

    with patch("agent.coordinator.build_app",
               return_value=(mock_runner, "run-session-id", MagicMock(), mock_session_service)):
        with patch("db.schema.init_db"):
            with patch("infra.observability.setup_observability"):
                with patch("tools.execution.tools.get_portfolio",
                           new=AsyncMock(return_value={
                               "positions": [{"symbol": "XLK"}],
                               "portfolio_value": 10000.0,
                           })):
                    from cli.main import _run_session
                    asyncio.run(_run_session(params))

    # If we get here without raising, the portfolio load success path ran


def test_run_session_keyboard_interrupt(tmp_db, monkeypatch):
    """Line 200: KeyboardInterrupt is caught and swallowed."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.session import SessionParams
    from models.enums import Strategy, OperatingMode

    params = SessionParams(
        strategy=Strategy.MOMENTUM,
        mode=OperatingMode.FULL_AUTO,
        loss_limit_eur=1000.0,
        timeframe_days=1,
        shortlist_n=1,
        hitl_timeout_seconds=30,
        hitl_timeout_action="confirm",
    )

    async def raise_keyboard(*args, **kwargs):
        raise KeyboardInterrupt()
        yield  # make it an async generator

    mock_runner = MagicMock()
    mock_runner.run_async = raise_keyboard

    mock_session_service = AsyncMock()

    # Should NOT raise — KeyboardInterrupt is caught internally
    with patch("agent.coordinator.build_app",
               return_value=(mock_runner, "ki-session-id", MagicMock(), mock_session_service)):
        with patch("db.schema.init_db"):
            with patch("infra.observability.setup_observability"):
                with patch("tools.execution.tools.get_portfolio",
                           new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})):
                    from cli.main import _run_session
                    asyncio.run(_run_session(params))


def test_run_cmd_confirms_and_runs(tmp_db, monkeypatch):
    """Line 137: asyncio.run(_run_session(params)) is called when user confirms 'yes'."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    async def noop_run_session(params):
        pass

    with patch("cli.main._run_session", new=noop_run_session):
        result = runner.invoke(
            app,
            ["run", "--strategy", "MOMENTUM", "--mode", "SEMI_AUTO",
             "--loss-limit", "500", "--timeframe", "3", "--shortlist-n", "2",
             "--hitl-timeout", "60", "--universe", "US_SECTOR_ETFS"],
            input="y\n",  # confirm
        )
    assert result.exit_code == 0


def test_status_cmd_with_unresolved_trade(tmp_db):
    """Lines 286-288: status_cmd prints each unresolved trade."""
    import sqlite3

    from db.schema import upsert_session

    upsert_session("sess-status-unresolved", "MOMENTUM", "SEMI_AUTO")

    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO trade_records (
            id, session_id, cycle_index, order_id, symbol, strategy,
            market_regime, side, qty, entry_price,
            optimist_verdict, pessimist_verdict, risk_level, risk_score,
            opt_win_rate_at_trade, pess_win_rate_at_trade,
            outcome_resolved, outcome_timed_out, executed_at
        ) VALUES (
            'unres-trade-1', 'sess-status-unresolved', 0, 'ORDER-UNRES', 'XLK', 'MOMENTUM',
            'BULL_TREND', 'buy', 5.0, 180.0,
            'LOW', 'MEDIUM', 'MEDIUM', 0.9,
            0.5, 0.5,
            0, 0, '2025-01-01T10:00:00'
        )
    """)
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    # Should show the unresolved trade warning
    assert "unresolved" in result.output.lower()


def test_run_session_portfolio_exception_path(tmp_db, monkeypatch):
    """Lines 172-173: when get_portfolio raises, a yellow warning is printed."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.session import SessionParams
    from models.enums import Strategy, OperatingMode

    params = SessionParams(
        strategy=Strategy.MOMENTUM,
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe_days=3,
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )

    # runner.run_async yields nothing (clean exit)
    async def no_events(*args, **kwargs):
        return
        yield  # make it an async generator

    mock_runner = MagicMock()
    mock_runner.run_async = no_events

    mock_session_service = AsyncMock()

    with patch("agent.coordinator.build_app",
               return_value=(mock_runner, "exc-sess-id", MagicMock(), mock_session_service)):
        with patch("db.schema.init_db"):
            with patch("infra.observability.setup_observability"):
                with patch("tools.execution.tools.get_portfolio",
                           new=AsyncMock(side_effect=RuntimeError("connection refused"))):
                    from cli.main import _run_session
                    # Should NOT raise — the portfolio exception is caught internally
                    asyncio.run(_run_session(params))


def test_cli_main_entrypoint_calls_app():
    """Line 337: __main__ block invokes app()."""
    import runpy
    # Patch Typer.__call__ at the class level so the re-imported app instance is intercepted
    with patch("typer.Typer.__call__") as mock_call:
        runpy.run_module("cli.main", run_name="__main__", alter_sys=False)
    mock_call.assert_called_once()
