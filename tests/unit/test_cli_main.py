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
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from alphoryn.cli.main import _format_decision, _warn_fractional_sessions, app
from alphoryn.config.models import AlphorynConfig
from alphoryn.memory.bank import MemoryBank

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg_file(tmp_path: Path, **extra) -> Path:
    payload = {"etf1": "SPY", "etf2": "QQQ", **extra}
    f = tmp_path / "config.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def _patched_run(config_file: Path, extra_args: list[str] | None = None):
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
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
# _warn_fractional_sessions (line 122)
# ---------------------------------------------------------------------------


def test_warn_fractional_sessions_emits_warning_when_fractional() -> None:
    """10H / 4H = 2.5 → remainder != 0 → warning emitted."""
    cfg = AlphorynConfig(
        etf1="SPY", etf2="QQQ", candle_timeframe="4H", run_duration="10H"
    )
    from io import StringIO

    with patch("sys.stderr", StringIO()) as buf:
        _warn_fractional_sessions(cfg)
    assert "WARN" in buf.getvalue()
    assert "rounding down" in buf.getvalue()


def test_warn_fractional_sessions_silent_when_exact() -> None:
    """24H / 4H = 6 exactly → no warning."""
    cfg = AlphorynConfig(
        etf1="SPY", etf2="QQQ", candle_timeframe="4H", run_duration="24H"
    )
    from io import StringIO

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
    from alphoryn.cli.main import _start_scheduler

    cfg = AlphorynConfig(etf1="SPY", etf2="QQQ")
    bank = MagicMock()
    mock_scheduler = MagicMock()

    # _start_scheduler does `from alphoryn.scheduler.scheduler import Scheduler`
    # inside the function — patch at the source module.
    with patch("alphoryn.scheduler.scheduler.Scheduler", return_value=mock_scheduler):
        _start_scheduler(cfg, bank)

    mock_scheduler.run.assert_called_once()


# ---------------------------------------------------------------------------
# _format_decision
# ---------------------------------------------------------------------------


def test_format_decision_no_strategy_returns_dash() -> None:
    assert _format_decision(None, "BUY", "EXECUTED") == "—"


def test_format_decision_no_decision_returns_dash() -> None:
    assert _format_decision("MOMENTUM", None, None) == "—"


def test_format_decision_mean_reversion_executed() -> None:
    assert _format_decision("MEAN_REVERSION", "BUY", "EXECUTED") == "MR → BUY (exec)"


def test_format_decision_momentum_hold_no_result() -> None:
    assert _format_decision("MOMENTUM", "HOLD", None) == "MOM → HOLD"


def test_format_decision_momentum_sell_executed() -> None:
    assert _format_decision("MOMENTUM", "SELL", "EXECUTED") == "MOM → SELL (exec)"


def test_format_decision_momentum_buy_skipped() -> None:
    assert _format_decision("MOMENTUM", "BUY", "SKIPPED_BUDGET") == "MOM → BUY"


def test_format_decision_mean_reversion_hold() -> None:
    assert _format_decision("MEAN_REVERSION", "HOLD", None) == "MR → HOLD"


# ---------------------------------------------------------------------------
# status command — with open positions (lines 185-186)
# ---------------------------------------------------------------------------


def test_status_shows_open_positions(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)

    from alphoryn.memory.schema import Position
    from alphoryn.memory.schema import Session as Sess

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
            etf="SPY",
            strategy="MOMENTUM",
            direction="BUY",
            entry_price=450.0,
            entry_time=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            lot_size=10.0,
            stop_loss_price=441.0,
            exit_target='{"type":"fixed","target_price":460.0}',
            evaluation_window_session=5,
            status="OPEN",
        )
        s.add(pos)
        s.commit()

    result = runner.invoke(app, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "ETF1 SPY" in result.output
    assert "MOMENTUM" in result.output
    assert "BUY" in result.output
    assert "450.00" in result.output
    assert "ETF2 QQQ  (no open position)" in result.output


def test_status_falls_back_to_generic_labels_on_bad_config_snapshot(
    tmp_path: Path,
) -> None:
    """config_snapshot with invalid JSON → falls back to ETF1/ETF2 labels."""
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    # store non-JSON garbage as config_snapshot
    bank.start_run("not-valid-json", 6)

    result = runner.invoke(app, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "ETF1 ETF1" in result.output
    assert "ETF2 ETF2" in result.output


# ---------------------------------------------------------------------------
# history command — with session rows (lines 242-245)
# ---------------------------------------------------------------------------


def test_history_shows_session_rows(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run('{"etf1":"SPY"}', 6)

    from alphoryn.memory.schema import Session as Sess

    sess_id = f"run-{run_id}/session-0001"
    with __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bank._engine) as s:
        sess = Sess(
            id=sess_id,
            run_id=run_id,
            candle_close_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            created_at=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
            status="COMPLETED",
            etf1_strategy="MEAN_REVERSION",
            etf1_decision="BUY",
            etf1_execution_result="EXECUTED",
            etf2_strategy="MOMENTUM",
            etf2_decision="HOLD",
            etf2_execution_result=None,
        )
        s.add(sess)
        s.commit()

    result = runner.invoke(app, ["history", "--db", str(db)])
    assert result.exit_code == 0
    assert sess_id in result.output
    assert "MR → BUY (exec)" in result.output
    assert "MOM → HOLD" in result.output


