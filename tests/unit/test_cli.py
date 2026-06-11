"""Unit tests for cli.main — Typer CLI commands."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
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
    monkeypatch.setattr("cli.main._connect", _connect)
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
    monkeypatch.setattr("cli.main.CONFIG_DIR", config_dir)
    monkeypatch.setattr("cli.main.CONFIG_FILE", config_file)
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
        ["run", "--mode", "SEMI_AUTO",
         "--loss-limit", "500", "--timeframe", "1Day", "--shortlist-n", "2",
         "--hitl-timeout", "60", "--universe", "US_SECTOR_ETFS", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output


def test_run_cmd_cancelled_by_user():
    """User says 'no' at confirm prompt — session should not start."""
    result = runner.invoke(
        app,
        ["run", "--mode", "SEMI_AUTO",
         "--loss-limit", "500", "--timeframe", "1Day", "--shortlist-n", "2",
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
        input="SEMI_AUTO\n500\n1Day\n2\n60\nUS_SECTOR_ETFS\n",
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output


def test_run_cmd_full_auto_skips_hitl_prompt():
    """FULL_AUTO mode doesn't prompt for HITL timeout when given directly."""
    result = runner.invoke(
        app,
        ["run", "--mode", "FULL_AUTO",
         "--loss-limit", "500", "--timeframe", "1Day", "--shortlist-n", "2",
         "--universe", "US_SECTOR_ETFS", "--dry-run"],
    )
    assert result.exit_code == 0


# ── history_cmd ───────────────────────────────────────────────────────────────

def test_history_cmd_empty_db(tmp_db):
    result = runner.invoke(app, ["history"])
    assert result.exit_code == 0
    assert "No sessions found" in result.output


def test_history_cmd_with_sessions(tmp_db):
    from db.schema import close_session, upsert_session
    upsert_session("sess-hist-1", "SEMI_AUTO")
    close_session("sess-hist-1", "clean", 50.0, 3)

    result = runner.invoke(app, ["history"])
    assert result.exit_code == 0
    assert "sess-hist-1"[:8] in result.output


def test_history_cmd_limit_option(tmp_db):
    from db.schema import upsert_session
    for i in range(5):
        upsert_session(f"sess-lim-{i}", "SEMI_AUTO")

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

    with patch("cli.main.get_alpaca_credentials",
               new=AsyncMock(return_value=("sm-key", "sm-secret"))):
        from cli.main import _load_alpaca_credentials
        key, secret = asyncio.run(_load_alpaca_credentials())

    assert key == "sm-key"
    assert secret == "sm-secret"


# ── _print_session_params (helper) ───────────────────────────────────────────

def test_print_session_params_does_not_raise():
    from cli.main import _print_session_params
    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
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

    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
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

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "mock-session-id", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})),
        pytest.raises(RuntimeError),
    ):
        from cli.main import _run_session
        asyncio.run(_run_session(params))

    # Credentials must be cleared
    assert os.environ.get("ALPACA_API_KEY") is None
    assert os.environ.get("ALPACA_API_SECRET") is None


def test_run_session_portfolio_load_success(tmp_db, monkeypatch):
    """Lines 172-173: portfolio loaded successfully → rprint message."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
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

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "run-session-id", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={
                  "positions": [{"symbol": "XLK"}],
                  "portfolio_value": 10000.0,
              })),
    ):
        from cli.main import _run_session
        asyncio.run(_run_session(params))

    # If we get here without raising, the portfolio load success path ran


def test_run_session_keyboard_interrupt(tmp_db, monkeypatch):
    """Line 200: KeyboardInterrupt is caught and swallowed."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.FULL_AUTO,
        loss_limit_eur=1000.0,
        timeframe="1Day",
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
    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "ki-session-id", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})),
    ):
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
            ["run", "--mode", "SEMI_AUTO",
             "--loss-limit", "500", "--timeframe", "1Day", "--shortlist-n", "2",
             "--hitl-timeout", "60", "--universe", "US_SECTOR_ETFS"],
            input="y\n",  # confirm
        )
    assert result.exit_code == 0


def test_status_cmd_with_unresolved_trade(tmp_db):
    """Lines 286-288: status_cmd prints each unresolved trade."""
    import sqlite3

    from db.schema import upsert_session

    upsert_session("sess-status-unresolved", "SEMI_AUTO")

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

    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
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

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "exc-sess-id", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(side_effect=RuntimeError("connection refused"))),
    ):
        from cli.main import _run_session
        # Should NOT raise — the portfolio exception is caught internally
        asyncio.run(_run_session(params))


def test_run_session_close_session_db_failure_is_swallowed(tmp_db, monkeypatch):
    """DB failure in close_session during finally does not prevent clean exit."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )

    async def no_events(*args, **kwargs):
        return
        yield  # make it an async generator

    mock_runner = MagicMock()
    mock_runner.run_async = no_events
    mock_session_service = AsyncMock()

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "fail-close-id", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})),
        patch("cli.main.close_session", side_effect=Exception("db broken")),
    ):
        from cli.main import _run_session
        asyncio.run(_run_session(params))  # must not raise


def test_run_session_sets_outcome_completed_in_db(tmp_db, monkeypatch):
    """On clean session end, close_session writes outcome='completed' to DB."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    from models.enums import OperatingMode
    from models.session import SessionParams

    params = SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )

    async def no_events(*args, **kwargs):
        return
        yield  # make it an async generator

    mock_runner = MagicMock()
    mock_runner.run_async = no_events
    mock_session_service = AsyncMock()

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "outcome-sess-id", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})),
    ):
        from cli.main import _run_session
        asyncio.run(_run_session(params))

    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(str(tmp_db))
    conn.row_factory = _sqlite3.Row
    row = conn.execute(
        "SELECT outcome, cycle_count FROM sessions WHERE id = 'outcome-sess-id'"
    ).fetchone()
    conn.close()
    assert row["outcome"] == "completed"
    assert row["cycle_count"] == 0


def test_cli_main_entrypoint_calls_app():
    """Line 337: __main__ block invokes app()."""
    import runpy
    # Patch Typer.__call__ at the class level so the re-imported app instance is intercepted
    with patch("typer.Typer.__call__") as mock_call:
        runpy.run_module("cli.main", run_name="__main__", alter_sys=False)
    mock_call.assert_called_once()


# ── _run_session: event type coverage ────────────────────────────────────────

def _make_session_params():
    from models.enums import OperatingMode
    from models.session import SessionParams
    return SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )


def test_run_session_empty_content_skipped(tmp_db, monkeypatch):
    """Line 221: event with no content is skipped via continue."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    params = _make_session_params()

    event_no_content = MagicMock()
    event_no_content.content = None  # triggers the continue branch

    event_with_text = MagicMock()
    mock_part = MagicMock(spec=["text"])
    mock_part.text = "Done."
    event_with_text.content = MagicMock()
    event_with_text.content.parts = [mock_part]

    async def fake_run_async(*args, **kwargs):
        yield event_no_content
        yield event_with_text

    mock_runner = MagicMock()
    mock_runner.run_async = fake_run_async
    mock_session_service = AsyncMock()

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "skip-sess", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})),
    ):
        from cli.main import _run_session
        asyncio.run(_run_session(params))  # must not raise


def test_run_session_function_call_event(tmp_db, monkeypatch):
    """Lines 226-229: part with function_call renders tool invocation line."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    params = _make_session_params()

    part_fc = MagicMock(spec=["function_call"])
    part_fc.function_call = MagicMock()
    part_fc.function_call.name = "market__get_ohlcv"
    part_fc.function_call.args = {"symbol": "XLK", "bars": 20}

    event = MagicMock()
    event.content = MagicMock()
    event.content.parts = [part_fc]

    async def fake_run_async(*args, **kwargs):
        yield event

    mock_runner = MagicMock()
    mock_runner.run_async = fake_run_async
    mock_session_service = AsyncMock()

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "fc-sess", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})),
    ):
        from cli.main import _run_session
        asyncio.run(_run_session(params))  # must not raise


def test_run_session_function_response_event(tmp_db, monkeypatch):
    """Lines 230-234: part with function_response renders summary."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    params = _make_session_params()

    part_fr = MagicMock(spec=["function_response"])
    part_fr.function_response = MagicMock()
    part_fr.function_response.name = "get_portfolio"
    part_fr.function_response.response = {
        "positions": [{"symbol": "XLK"}],
        "portfolio_value": 10000.0,
        "cash_usd": 5000.0,
    }

    event = MagicMock()
    event.content = MagicMock()
    event.content.parts = [part_fr]

    async def fake_run_async(*args, **kwargs):
        yield event

    mock_runner = MagicMock()
    mock_runner.run_async = fake_run_async
    mock_session_service = AsyncMock()

    with (
        patch("cli.main.build_app",
              return_value=(mock_runner, "fr-sess", MagicMock(), mock_session_service)),
        patch("cli.main.init_db"),
        patch("cli.main.setup_observability"),
        patch("cli.main.get_portfolio",
              new=AsyncMock(return_value={"positions": [], "portfolio_value": 0.0})),
    ):
        from cli.main import _run_session
        asyncio.run(_run_session(params))  # must not raise


# ── _summarise_tool_response ──────────────────────────────────────────────────

def test_summarise_empty_resp():
    from cli.main import _summarise_tool_response
    assert _summarise_tool_response("anything", {}) == "(empty)"


def test_summarise_get_ohlcv_with_bars():
    from cli.main import _summarise_tool_response
    resp = {
        "symbol": "XLK",
        "bars": [{"close": 185.0}, {"close": 186.0}],
    }
    result = _summarise_tool_response("get_ohlcv", resp)
    assert "XLK" in result
    assert "2 bars" in result
    assert "last close" in result


def test_summarise_get_ohlcv_zero_bars():
    from cli.main import _summarise_tool_response
    resp = {"symbol": "XLK", "bars": []}
    result = _summarise_tool_response("get_ohlcv", resp)
    assert "0 bars" in result


def test_summarise_screen_etfs():
    from cli.main import _summarise_tool_response
    resp = {
        "results": [
            {"symbol": "XLK"},
            {"symbol": "XLE"},
        ]
    }
    result = _summarise_tool_response("screen_etfs", resp)
    assert "2 ETFs" in result
    assert "XLK" in result


def test_summarise_score_technical():
    from cli.main import _summarise_tool_response
    resp = {"symbol": "XLK", "score": 0.75, "signal": "buy", "regime_fit": 0.9}
    result = _summarise_tool_response("score_technical", resp)
    assert "XLK" in result
    assert "0.75" in result


def test_summarise_score_momentum():
    from cli.main import _summarise_tool_response
    resp = {"symbol": "SPY", "score": 0.6, "signal": "hold", "regime_fit": 0.7}
    result = _summarise_tool_response("score_momentum", resp)
    assert "SPY" in result


def test_summarise_detect_market_regime():
    from cli.main import _summarise_tool_response
    resp = {
        "regime": "BULL_TREND",
        "vix": 15.2,
        "benchmark_symbol": "SPY",
        "benchmark_return_20d": 3.5,
    }
    result = _summarise_tool_response("detect_market_regime", resp)
    assert "BULL_TREND" in result
    assert "15.2" in result


def test_summarise_get_macro_data():
    from cli.main import _summarise_tool_response
    resp = {"vix": 18.5, "yield_10y": 4.2, "dxy": 104.3}
    result = _summarise_tool_response("get_macro_data", resp)
    assert "18.5" in result
    assert "4.2" in result


def test_summarise_get_quote():
    from cli.main import _summarise_tool_response
    resp = {"symbol": "XLK", "bid": 180.0, "ask": 180.05}
    result = _summarise_tool_response("get_quote", resp)
    assert "XLK" in result
    assert "180.0" in result


def test_summarise_get_calibration_with_data():
    from cli.main import _summarise_tool_response
    resp = {
        "has_data": True,
        "opt_win_rate": 0.6,
        "pess_win_rate": 0.4,
        "trade_count": 10,
    }
    result = _summarise_tool_response("get_calibration", resp)
    assert "60%" in result
    assert "40%" in result


def test_summarise_get_calibration_no_data():
    from cli.main import _summarise_tool_response
    resp = {"has_data": False}
    result = _summarise_tool_response("get_calibration", resp)
    assert "no calibration" in result


def test_summarise_get_portfolio():
    from cli.main import _summarise_tool_response
    resp = {
        "positions": [{"symbol": "XLK"}],
        "portfolio_value": 10000.0,
        "cash_usd": 5000.0,
    }
    result = _summarise_tool_response("get_portfolio", resp)
    assert "1 positions" in result
    assert "10,000" in result


def test_summarise_write_trade():
    from cli.main import _summarise_tool_response
    resp = {"trade_id": "t-123", "written": True, "extra": "ignored"}
    result = _summarise_tool_response("write_trade", resp)
    assert "t-123" in result


def test_summarise_record_cycle():
    from cli.main import _summarise_tool_response
    resp = {"cycle_index": 1, "outcome": "completed"}
    result = _summarise_tool_response("record_cycle", resp)
    assert "1" in result


def test_summarise_generic_fallback():
    from cli.main import _summarise_tool_response
    resp = {"status": "ok", "count": 5, "nested": {"ignored": True}}
    result = _summarise_tool_response("unknown_tool", resp)
    assert "status" in result
    assert "ok" in result


def test_summarise_generic_fallback_all_complex():
    from cli.main import _summarise_tool_response
    resp = {"nested": {"a": 1}, "list": [1, 2, 3]}
    result = _summarise_tool_response("unknown_tool", resp)
    assert result == "(ok)"
