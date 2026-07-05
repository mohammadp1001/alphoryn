"""Integration tests for the full startup cycle (T020).

Unlike the contract tests, these use a real SQLite memory bank on the
filesystem rather than a mocked MemoryBank class. External network calls
(Secret Manager, Alpaca API) are still stubbed.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from alphoryn.cli.main import app
from alphoryn.memory.bank import MemoryBank
from alphoryn.secrets.client import SecretsError

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(cfg_path: Path, db_path: Path, **fields) -> Path:
    defaults = {"etf1": "SPY", "etf2": "QQQ", "memory_db_path": str(db_path)}
    defaults.update(fields)
    cfg_path.write_text(json.dumps(defaults), encoding="utf-8")
    return cfg_path


def _patched_run(config_file: Path, extra_args: list[str] | None = None):
    """Run `alphoryn run` with real MemoryBank but stubbed secrets and scheduler."""
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main._start_scheduler"),
    ):
        args = ["run", "--config", str(config_file)] + (extra_args or [])
        return runner.invoke(app, args)


# ---------------------------------------------------------------------------
# Valid startup
# ---------------------------------------------------------------------------


def test_valid_config_startup_produces_banner(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    cfg = _write_config(tmp_path / "config.json", db)
    result = _patched_run(cfg)
    assert result.exit_code == 0
    assert "Alphoryn v0.0.1 — Paper Trading" in result.output
    assert "ETFs: SPY / QQQ" in result.output


def test_session_count_matches_config(tmp_path: Path) -> None:
    """4H timeframe, 24H run → 6 sessions planned."""
    db = tmp_path / "memory.db"
    cfg = _write_config(tmp_path / "config.json", db, candle_timeframe="4H", run_duration="24H")
    result = _patched_run(cfg)
    assert result.exit_code == 0
    assert "Sessions planned: 6" in result.output


def test_session_count_1h_24h(tmp_path: Path) -> None:
    """1H timeframe, 24H run → 24 sessions planned."""
    db = tmp_path / "memory.db"
    cfg = _write_config(tmp_path / "config.json", db, candle_timeframe="1H", run_duration="24H")
    result = _patched_run(cfg)
    assert result.exit_code == 0
    assert "Sessions planned: 24" in result.output


def test_memory_bank_db_file_created_on_startup(tmp_path: Path) -> None:
    """SQLite file is created at the configured memory_db_path."""
    db = tmp_path / "memory.db"
    cfg = _write_config(tmp_path / "config.json", db)
    assert not db.exists()
    _patched_run(cfg)
    assert db.exists()


def test_startup_reads_zero_open_positions_from_real_db(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    cfg = _write_config(tmp_path / "config.json", db)
    result = _patched_run(cfg)
    assert result.exit_code == 0
    assert "0 open positions loaded" in result.output


def test_startup_reads_preexisting_open_position_from_real_db(tmp_path: Path) -> None:
    """Pre-populated OPEN position is reported at startup."""
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    run_id = bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)

    from alphoryn.memory.schema import Position
    from alphoryn.memory.schema import Session as Sess
    import sqlalchemy.orm as orm

    sess_id = f"run-{run_id}/session-0001"
    with orm.Session(bank._engine) as s:
        s.add(
            Sess(
                id=sess_id,
                run_id=run_id,
                candle_close_at=datetime(2024, 1, 15, 15, 0),
                created_at=datetime(2024, 1, 15, 15, 0),
                status="COMPLETED",
            )
        )
        s.commit()
        s.add(
            Position(
                session_id=sess_id,
                etf="SPY",
                strategy="MOMENTUM",
                direction="BUY",
                entry_price=450.0,
                entry_time=datetime(2024, 1, 15, 15, 0),
                lot_size=10.0,
                stop_loss_price=441.0,
                exit_target='{"type":"trailing_stop","trail_pct":0.015}',
                evaluation_window_session=5,
                status="OPEN",
            )
        )
        s.commit()

    cfg = _write_config(tmp_path / "config.json", db)
    result = _patched_run(cfg)
    assert result.exit_code == 0
    assert "1 open position loaded" in result.output


# ---------------------------------------------------------------------------
# Fractional session warning
# ---------------------------------------------------------------------------


def test_fractional_session_count_emits_warning(tmp_path: Path) -> None:
    """10H / 4H = 2.5 → rounds down to 2, WARN emitted."""
    db = tmp_path / "memory.db"
    cfg = _write_config(tmp_path / "config.json", db, candle_timeframe="4H", run_duration="10H")
    result = _patched_run(cfg)
    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "rounding down" in result.output


# ---------------------------------------------------------------------------
# Exit code 1 — config errors
# ---------------------------------------------------------------------------


def test_invalid_config_missing_required_fields_exit_code_1(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"candle_timeframe": "1H"}), encoding="utf-8")
    result = runner.invoke(app, ["run", "--config", str(cfg)])
    assert result.exit_code == 1


def test_malformed_json_config_exit_code_1(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("not valid json", encoding="utf-8")
    result = runner.invoke(app, ["run", "--config", str(cfg)])
    assert result.exit_code == 1


def test_missing_config_file_exit_code_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", "--config", str(tmp_path / "nonexistent.json")]
    )
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Exit code 2 — memory bank errors
# ---------------------------------------------------------------------------


def test_corrupt_memory_bank_exit_code_2(tmp_path: Path) -> None:
    bad_db = tmp_path / "bad.db"
    bad_db.write_bytes(b"NOT SQLITE\xff")
    cfg = _write_config(tmp_path / "config.json", bad_db)
    with patch("alphoryn.cli.main.load_alpaca_credentials"):
        result = runner.invoke(app, ["run", "--config", str(cfg)])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Exit code 3 — Secret Manager errors
# ---------------------------------------------------------------------------


def test_secret_manager_unreachable_exit_code_3(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    cfg = _write_config(tmp_path / "config.json", db)
    with patch(
        "alphoryn.cli.main.load_alpaca_credentials",
        side_effect=SecretsError("unreachable"),
    ):
        result = runner.invoke(app, ["run", "--config", str(cfg)])
    assert result.exit_code == 3
