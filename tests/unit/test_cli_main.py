"""Unit tests for alphoryn/cli/main.py (T017 scope).

Covers branches not exercised by the T014 contract tests:
- CLI flag overrides (exchange, timeframe, duration, budget=0, stop_loss)
- _warn_fractional_sessions when remainder != 0
- _start_scheduler function body
- _format_decision all branches
- status command with open positions
- history command with session rows
- __main__ entrypoint
"""

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from alphoryn.cli.main import (
    _format_decision,
    _start_scheduler,
    _warn_fractional_sessions,
    app,
)

# _real_reconcile_broker_state is bound at import time, before the autouse
# fixture below patches the module attribute: the reconciliation tests need
# the real function rather than that stub.
from alphoryn.cli.main import _reconcile_broker_state as _real_reconcile_broker_state
from alphoryn.config.models import AlphorynConfig
from alphoryn.memory.bank import MemoryBank, MemoryBankError
from alphoryn.memory.schema import Position
from alphoryn.memory.schema import Session as Sess
from alphoryn.telemetry.otel import TelemetrySetupError

runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_broker_reconciliation():
    """Neutralise the startup reconciliation for every test in this module.

    It builds a real TradingClient and calls Alpaca, so leaving it live would
    make these tests depend on whether the machine has credentials - green on
    a developer box, red in CI. Tests about reconciliation patch over this.
    """
    with patch("alphoryn.cli.main._reconcile_broker_state") as m:
        yield m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg_file(tmp_path: Path, **extra) -> Path:
    payload = {"tickers": ["SPY", "QQQ"], **extra}
    f = tmp_path / "config.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def _patched_run(config_file: Path, extra_args: list[str] | None = None):
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
        patch("alphoryn.cli.main.setup_otel"),
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = []
        mock_bank_cls.return_value = mock_bank
        args = ["run", "--config", str(config_file)] + (extra_args or [])
        return runner.invoke(app, args)


# ---------------------------------------------------------------------------
# CLI flag overrides (lines 62, 64, 66, 68, 70)
# ---------------------------------------------------------------------------


def test_run_exchange_override(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    result = _patched_run(cfg_file, ["--exchange", "NYSE"])
    assert result.exit_code == 0


def test_run_timeframe_override(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    result = _patched_run(cfg_file, ["--timeframe", "4H"])
    assert result.exit_code == 0
    assert "Timeframe: 4H" in result.output


def test_run_duration_override(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    result = _patched_run(cfg_file, ["--duration", "8H"])
    assert result.exit_code == 0
    assert "Duration: 8H" in result.output


def test_run_budget_positive_override(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    result = _patched_run(cfg_file, ["--budget", "500"])
    assert result.exit_code == 0


def test_run_budget_zero_means_no_limit(tmp_path: Path) -> None:
    """--budget 0 sets session_money_budget=None (no limit)."""
    cfg_file = _cfg_file(tmp_path)
    result = _patched_run(cfg_file, ["--budget", "0"])
    assert result.exit_code == 0


def test_run_stop_loss_override(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    result = _patched_run(cfg_file, ["--stop-loss", "0.05"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# setup_otel integration in run()
# ---------------------------------------------------------------------------


def test_run_calls_setup_otel(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
        patch("alphoryn.cli.main.setup_otel") as mock_setup_otel,
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = []
        mock_bank_cls.return_value = mock_bank
        runner.invoke(app, ["run", "--config", str(cfg_file)])
    mock_setup_otel.assert_called_once()


# ---------------------------------------------------------------------------
# _warn_fractional_sessions (line 122)
# ---------------------------------------------------------------------------


def test_warn_fractional_sessions_emits_warning_when_fractional() -> None:
    """10H / 4H = 2.5 -> remainder != 0 -> warning emitted."""
    cfg = AlphorynConfig(
        tickers=["SPY", "QQQ"], candle_timeframe="4H", run_duration="10H"
    )
    with patch("sys.stderr", StringIO()) as buf:
        _warn_fractional_sessions(cfg)
    assert "WARN" in buf.getvalue()
    assert "rounding down" in buf.getvalue()


def test_warn_fractional_sessions_silent_when_exact() -> None:
    """24H / 4H = 6 exactly -> no warning."""
    cfg = AlphorynConfig(
        tickers=["SPY", "QQQ"], candle_timeframe="4H", run_duration="24H"
    )
    with patch("sys.stderr", StringIO()) as buf:
        _warn_fractional_sessions(cfg)
    assert buf.getvalue() == ""


def test_fractional_session_warning_appears_in_run_output(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path, candle_timeframe="4H", run_duration="10H")
    result = _patched_run(cfg_file)
    assert result.exit_code == 0
    assert "WARN" in result.output


# ---------------------------------------------------------------------------
# _start_scheduler (lines 131-134)
# ---------------------------------------------------------------------------


def test_start_scheduler_creates_and_runs_scheduler() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    bank = MagicMock()
    mock_scheduler = MagicMock()

    with patch("alphoryn.cli.main.Scheduler", return_value=mock_scheduler):
        _start_scheduler(cfg, bank)

    mock_scheduler.run.assert_called_once()


def test_start_scheduler_wires_position_monitor() -> None:
    """Regression for #120: the monitor must be constructed and handed over."""
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    bank = MagicMock()

    with (
        patch("alphoryn.cli.main.Scheduler") as mock_scheduler_cls,
        patch("alphoryn.cli.main.PositionMonitor") as mock_monitor_cls,
    ):
        _start_scheduler(cfg, bank)

    monitor_kwargs = mock_monitor_cls.call_args.kwargs
    assert monitor_kwargs["bank"] is bank
    scheduler_kwargs = mock_scheduler_cls.call_args.kwargs
    assert scheduler_kwargs["monitor"] is mock_monitor_cls.return_value
    # Scheduler and monitor must share the same stop signal.
    assert scheduler_kwargs["monitor_stop_event"] is monitor_kwargs["stop_event"]


# ---------------------------------------------------------------------------
# _format_decision
# ---------------------------------------------------------------------------


def test_format_decision_no_strategy_returns_dash() -> None:
    assert _format_decision(None, "BUY", "EXECUTED") == "—"


def test_format_decision_no_decision_returns_dash() -> None:
    assert _format_decision("MOMENTUM", None, None) == "—"


def test_format_decision_mean_reversion_executed() -> None:
    assert _format_decision("MEAN_REVERSION", "BUY", "EXECUTED") == "MR -> BUY (exec)"


def test_format_decision_momentum_hold_no_result() -> None:
    assert _format_decision("MOMENTUM", "HOLD", None) == "MOM -> HOLD"


def test_format_decision_momentum_sell_executed() -> None:
    assert _format_decision("MOMENTUM", "SELL", "EXECUTED") == "MOM -> SELL (exec)"


def test_format_decision_momentum_buy_skipped() -> None:
    assert _format_decision("MOMENTUM", "BUY", "SKIPPED_BUDGET") == "MOM -> BUY"


def test_format_decision_mean_reversion_hold() -> None:
    assert _format_decision("MEAN_REVERSION", "HOLD", None) == "MR -> HOLD"


# ---------------------------------------------------------------------------
# status command — with open positions (lines 185-186)
# ---------------------------------------------------------------------------


def test_status_shows_open_positions(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    sess_id = f"run-{run_id}/session-0001"
    with __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bank._engine) as s:
        sess = Sess(
            id=sess_id,
            run_id=run_id,
            candle_close_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            created_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            status="COMPLETED",
        )
        s.add(sess)
        s.commit()
        pos = Position(
            session_id=sess_id,
            ticker="SPY",
            strategy="MOMENTUM",
            direction="BUY",
            entry_price=450.0,
            entry_time=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            lot_size=10.0,
            stop_loss_price=441.0,
            exit_target='{"type":"fixed","target_price":460.0}',
            evaluation_window_close_at=datetime(2024, 1, 15, 19, 0),
            status="OPEN",
        )
        s.add(pos)
        s.commit()

    result = runner.invoke(app, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "SPY" in result.output
    assert "MOMENTUM" in result.output
    assert "BUY" in result.output
    assert "450.00" in result.output
    assert "QQQ  (no open position)" in result.output


def test_status_falls_back_to_empty_list_on_bad_config_snapshot(
    tmp_path: Path,
) -> None:
    """config_snapshot with invalid JSON -> run_tickers=[] -> no ticker rows shown."""
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    bank.start_run("not-valid-json", 6)

    result = runner.invoke(app, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "Open positions:" in result.output


# ---------------------------------------------------------------------------
# history command — with session rows (lines 242-245)
# ---------------------------------------------------------------------------


def test_history_bad_config_snapshot_falls_back_to_decisions_column(tmp_path: Path) -> None:
    """Bad JSON in config_snapshot -> col_tickers=[] -> uses 'Decisions' header."""
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run("not-valid-json", 6)

    sess_id = f"run-{run_id}/session-0001"
    with __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bank._engine) as s:
        sess = Sess(
            id=sess_id,
            run_id=run_id,
            candle_close_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            created_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            status="COMPLETED",
            ticker_decisions=json.dumps({"SPY": {"strategy": "MOMENTUM", "decision": "BUY"}}),
        )
        s.add(sess)
        s.commit()

    result = runner.invoke(app, ["history", "--db", str(db)])
    assert result.exit_code == 0
    assert "Decisions" in result.output


def test_history_bad_ticker_decisions_json_falls_back_to_empty(tmp_path: Path) -> None:
    """Bad JSON in ticker_decisions -> td={} -> no decision columns rendered."""
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    sess_id = f"run-{run_id}/session-0001"
    with __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bank._engine) as s:
        sess = Sess(
            id=sess_id,
            run_id=run_id,
            candle_close_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            created_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            status="COMPLETED",
            ticker_decisions="not-valid-json",
        )
        s.add(sess)
        s.commit()

    result = runner.invoke(app, ["history", "--db", str(db)])
    assert result.exit_code == 0
    assert sess_id in result.output


def test_history_shows_session_rows(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    sess_id = f"run-{run_id}/session-0001"
    with __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bank._engine) as s:
        sess = Sess(
            id=sess_id,
            run_id=run_id,
            candle_close_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            created_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            status="COMPLETED",
            ticker_decisions=json.dumps({
                "SPY": {"strategy": "MEAN_REVERSION", "decision": "BUY"},
                "QQQ": {"strategy": "MOMENTUM", "decision": "HOLD"},
            }),
        )
        s.add(sess)
        s.commit()

    result = runner.invoke(app, ["history", "--db", str(db)])
    assert result.exit_code == 0
    assert sess_id in result.output
    assert "MR -> BUY" in result.output
    assert "MOM -> HOLD" in result.output


def test_history_renders_the_execution_marker(tmp_path: Path) -> None:
    """Issue #131: the '(exec)' branch was unreachable - callers always passed None."""
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run('{"tickers":["SPY"]}', 6)

    with __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bank._engine) as s:
        s.add(
            Sess(
                id=f"run-{run_id}/session-0001",
                run_id=run_id,
                candle_close_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
                created_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
                status="COMPLETED",
                ticker_decisions=json.dumps({
                    "SPY": {
                        "strategy": "MEAN_REVERSION",
                        "decision": "BUY",
                        "execution_result": "EXECUTED",
                    },
                }),
            )
        )
        s.commit()

    result = runner.invoke(app, ["history", "--db", str(db)])
    assert result.exit_code == 0
    assert "MR -> BUY (exec)" in result.output


# ---------------------------------------------------------------------------
# Utility Commands Tests: version, verify-telemetry, reset
# ---------------------------------------------------------------------------


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "Alphoryn v0.0.1" in result.output


def test_verify_telemetry_command(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    bank.start_run('{"tickers":["SPY"]}', 6)
    result = runner.invoke(app, ["verify-telemetry", "--db", str(db)])
    assert result.exit_code == 0
    assert "Telemetry check for" in result.output
    assert "Runs recorded: 1" in result.output


def test_reset_command(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    assert db.exists()
    bank._engine.dispose()

    result = runner.invoke(app, ["reset", "--db", str(db), "--force"])
    assert result.exit_code == 0
    assert "Reset memory bank database" in result.output
    assert not db.exists()


def test_reset_command_cancellation(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    result = runner.invoke(app, ["reset", "--db", str(db)], input="n\n")
    assert result.exit_code == 0
    assert "Reset cancelled." in result.output
    assert db.exists()
    bank._engine.dispose()


def test_reset_command_confirmed_at_the_prompt(tmp_path: Path) -> None:
    """Answering yes deletes the database, same as --force."""
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    bank._engine.dispose()

    result = runner.invoke(app, ["reset", "--db", str(db)], input="y\n")

    assert result.exit_code == 0
    assert "Reset memory bank database" in result.output
    assert not db.exists()


def test_reset_command_on_missing_database(tmp_path: Path) -> None:
    """Nothing to reset is not an error - say so and stop."""
    db = tmp_path / "never-created.db"

    result = runner.invoke(app, ["reset", "--db", str(db)])

    assert result.exit_code == 0
    assert "does not exist" in result.output


def test_verify_telemetry_reports_a_broken_memory_bank(tmp_path: Path) -> None:
    """An unopenable bank exits 2 rather than raising at the user."""
    db = tmp_path / "memory.db"
    with patch("alphoryn.cli.main.MemoryBank", side_effect=MemoryBankError("disk is read-only")):
        result = runner.invoke(app, ["verify-telemetry", "--db", str(db)])

    assert result.exit_code == 2
    assert "Memory bank error: disk is read-only" in result.output

# ---------------------------------------------------------------------------
# Telemetry preflight (exit 4)
# ---------------------------------------------------------------------------


def test_run_exits_4_when_telemetry_cannot_be_set_up(tmp_path: Path) -> None:
    """An untraced run leaves no record of why it traded, so it must not start."""
    cfg_file = _cfg_file(tmp_path)
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank"),
        patch("alphoryn.cli.main._start_scheduler") as mock_start,
        patch(
            "alphoryn.cli.main.setup_otel",
            side_effect=TelemetrySetupError("no credentials"),
        ),
    ):
        result = runner.invoke(app, ["run", "--config", str(cfg_file)])
    assert result.exit_code == 4
    assert "Telemetry error: no credentials" in result.output
    mock_start.assert_not_called()


def test_run_reports_the_gcp_project_traces_land_in(tmp_path: Path) -> None:
    """Telemetry going to the wrong project looks exactly like none at all."""
    cfg_file = _cfg_file(tmp_path)
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
        patch("alphoryn.cli.main.setup_otel", return_value="alphoryn"),
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = []
        mock_bank_cls.return_value = mock_bank
        result = runner.invoke(app, ["run", "--config", str(cfg_file)])
    assert result.exit_code == 0
    assert "Telemetry -> GCP project 'alphoryn'" in result.output


# ---------------------------------------------------------------------------
# Startup reconciliation (_reconcile_broker_state)
# ---------------------------------------------------------------------------


def _run_reconcile(*, discrepancies=None, apply_fixes=False, side_effect=None,
                   resolve_messages=None):
    """Drive _reconcile_broker_state with check_positions/resolve patched."""
    bank = MagicMock()
    with (
        patch("alphoryn.cli.main.TradingClient"),
        patch("alphoryn.cli.main.TelemetryLogger"),
        patch("alphoryn.cli.main.check_positions") as mock_check,
        patch("alphoryn.cli.main.resolve") as mock_resolve,
    ):
        if side_effect is not None:
            mock_check.side_effect = side_effect
        else:
            mock_check.return_value = discrepancies or []
        mock_resolve.return_value = resolve_messages or []
        buf = StringIO()
        err = StringIO()
        with patch("sys.stdout", buf), patch("sys.stderr", err):
            _real_reconcile_broker_state(bank, apply_fixes=apply_fixes)
        return buf.getvalue() + err.getvalue(), mock_resolve, bank


def _discrepancy(kind="ORPHAN", ticker="QQQ"):
    from alphoryn.reconcile.positions import Discrepancy

    if kind == "ORPHAN":
        return Discrepancy(ticker, kind, None, 113.0, ())
    return Discrepancy(ticker, kind, 2.0, None, (7,))


def test_reconcile_reports_agreement_when_nothing_differs() -> None:
    output, mock_resolve, _ = _run_reconcile()
    assert "reconciled" in output.lower()
    mock_resolve.assert_not_called()


def test_reconcile_prints_every_discrepancy() -> None:
    output, _, _ = _run_reconcile(
        discrepancies=[_discrepancy(ticker="QQQ"), _discrepancy(ticker="SPY")]
    )
    assert "QQQ" in output
    assert "SPY" in output
    assert "2 ticker(s)" in output


def test_reconcile_does_not_fix_without_the_flag() -> None:
    """The default is report-only: nothing destructive from a plain run."""
    _, mock_resolve, _ = _run_reconcile(discrepancies=[_discrepancy()])
    mock_resolve.assert_not_called()


def test_reconcile_warns_that_it_is_continuing_anyway() -> None:
    output, _, _ = _run_reconcile(discrepancies=[_discrepancy()])
    assert "--reconcile" in output
    assert "continuing anyway" in output


def test_reconcile_flag_resolves_the_discrepancies() -> None:
    _, mock_resolve, bank = _run_reconcile(
        discrepancies=[_discrepancy()], apply_fixes=True
    )
    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.kwargs["bank"] is bank


def test_reconcile_flag_prints_what_it_did() -> None:
    output, _, _ = _run_reconcile(
        discrepancies=[_discrepancy()],
        apply_fixes=True,
        resolve_messages=["QQQ: reconciled (ORPHAN)"],
    )
    assert "QQQ: reconciled (ORPHAN)" in output


def test_reconcile_warns_and_continues_when_the_broker_is_unreachable() -> None:
    """A check that could stop trading would be worse than the drift."""
    from alphoryn.reconcile.positions import ReconcileError

    output, mock_resolve, _ = _run_reconcile(
        side_effect=ReconcileError("Cannot list Alpaca positions: timeout")
    )
    assert "reconciliation skipped" in output
    assert "timeout" in output
    mock_resolve.assert_not_called()


def test_run_invokes_reconciliation_before_the_scheduler(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
        patch("alphoryn.cli.main.setup_otel", return_value="alphoryn"),
        patch("alphoryn.cli.main._reconcile_broker_state") as mock_reconcile,
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = []
        mock_bank_cls.return_value = mock_bank
        result = runner.invoke(app, ["run", "--config", str(cfg_file)])
    assert result.exit_code == 0
    mock_reconcile.assert_called_once()
    assert mock_reconcile.call_args.kwargs["apply_fixes"] is False


def test_run_passes_the_reconcile_flag_through(tmp_path: Path) -> None:
    cfg_file = _cfg_file(tmp_path)
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
        patch("alphoryn.cli.main.setup_otel", return_value="alphoryn"),
        patch("alphoryn.cli.main._reconcile_broker_state") as mock_reconcile,
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = []
        mock_bank_cls.return_value = mock_bank
        result = runner.invoke(app, ["run", "--config", str(cfg_file), "--reconcile"])
    assert result.exit_code == 0
    assert mock_reconcile.call_args.kwargs["apply_fixes"] is True
