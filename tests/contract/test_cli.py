"""Contract tests for the Alphoryn CLI.

Verifies that startup output format, exit codes, and command structure
match the specification in contracts/cli.md.
"""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from alphoryn.cli.main import app
from alphoryn.config.loader import load_config
from alphoryn.memory.bank import MemoryBank, MemoryBankError
from alphoryn.secrets.client import SecretsError

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI escape codes from Typer/Rich output."""
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    cfg = {"tickers": ["SPY", "QQQ"]}
    f = tmp_path / "config.json"
    f.write_text(json.dumps(cfg), encoding="utf-8")
    return f


def _patched_run(config_file: Path, extra_args: list[str] | None = None):
    """Invoke `alphoryn run` with all network dependencies patched out."""
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
# Startup banner and output lines
# ---------------------------------------------------------------------------


def test_startup_banner_present(config_file: Path) -> None:
    result = _patched_run(config_file)
    assert result.exit_code == 0, result.output
    assert "Alphoryn v0.0.1 — Paper Trading" in result.output


def test_startup_tickers_timeframe_duration_line(config_file: Path) -> None:
    result = _patched_run(config_file)
    assert "Tickers: SPY, QQQ" in result.output
    assert "Timeframe: 1H" in result.output
    assert "Duration: 24H" in result.output


def test_sessions_planned_line(config_file: Path) -> None:
    result = _patched_run(config_file)
    assert re.search(r"Sessions planned: \d+", result.output)


def test_memory_bank_line_zero_positions(config_file: Path) -> None:
    result = _patched_run(config_file)
    assert re.search(r"Memory bank: .+ — 0 open positions loaded", result.output)


def test_memory_bank_line_plural_positions(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"tickers": ["SPY", "QQQ"]}), encoding="utf-8")
    mock_pos1 = MagicMock()
    mock_pos2 = MagicMock()
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = [mock_pos1, mock_pos2]
        mock_bank_cls.return_value = mock_bank
        result = runner.invoke(app, ["run", "--config", str(cfg_file)])
    assert "2 open positions loaded" in result.output


def test_memory_bank_line_singular_position(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"tickers": ["SPY", "QQQ"]}), encoding="utf-8")
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = [MagicMock()]
        mock_bank_cls.return_value = mock_bank
        result = runner.invoke(app, ["run", "--config", str(cfg_file)])
    assert "1 open position loaded" in result.output


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_exit_code_1_on_invalid_config(tmp_path: Path) -> None:
    """Invalid config (missing tickers) → exit code 1."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"candle_timeframe": "1H"}), encoding="utf-8")
    result = runner.invoke(app, ["run", "--config", str(cfg_file)])
    assert result.exit_code == 1


def test_exit_code_1_on_bad_json(tmp_path: Path) -> None:
    """Malformed JSON config → exit code 1."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("not json", encoding="utf-8")
    result = runner.invoke(app, ["run", "--config", str(cfg_file)])
    assert result.exit_code == 1


def test_exit_code_2_on_inaccessible_memory_bank(config_file: Path) -> None:
    """Inaccessible / corrupt memory bank → exit code 2."""
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch(
            "alphoryn.cli.main.MemoryBank",
            side_effect=MemoryBankError("corrupt"),
        ),
    ):
        result = runner.invoke(app, ["run", "--config", str(config_file)])
    assert result.exit_code == 2


def test_exit_code_3_on_secret_manager_unreachable(config_file: Path) -> None:
    """Secret Manager unreachable at startup → exit code 3."""
    with patch(
        "alphoryn.cli.main.load_alpaca_credentials",
        side_effect=SecretsError("unreachable"),
    ):
        result = runner.invoke(app, ["run", "--config", str(config_file)])
    assert result.exit_code == 3


# ---------------------------------------------------------------------------
# CLI flag overrides
# ---------------------------------------------------------------------------


def test_run_cli_tickers_override(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"tickers": ["SPY", "QQQ"]}), encoding="utf-8")
    with (
        patch("alphoryn.cli.main.load_alpaca_credentials"),
        patch("alphoryn.cli.main.MemoryBank") as mock_bank_cls,
        patch("alphoryn.cli.main._start_scheduler"),
    ):
        mock_bank = MagicMock()
        mock_bank.load_open_positions.return_value = []
        mock_bank_cls.return_value = mock_bank
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_file), "--tickers", "IVV,DIA"],
        )
    assert "Tickers: IVV, DIA" in result.output


# ---------------------------------------------------------------------------
# alphoryn status command
# ---------------------------------------------------------------------------


def test_status_command_exists() -> None:
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "--db" in _plain(result.output)


def test_status_shows_no_runs_when_db_empty(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    result = runner.invoke(app, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_status_shows_current_run(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    result = runner.invoke(app, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "Current run:" in result.output
    assert "Sessions:" in result.output
    assert "Open positions:" in result.output


def test_status_exit_code_2_on_bad_db(tmp_path: Path) -> None:
    bad_db = tmp_path / "bad.db"
    bad_db.write_bytes(b"NOT SQLITE\xff")
    result = runner.invoke(app, ["status", "--db", str(bad_db)])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# alphoryn history command
# ---------------------------------------------------------------------------


def test_history_command_exists() -> None:
    result = runner.invoke(app, ["history", "--help"])
    assert result.exit_code == 0
    plain = _plain(result.output)
    assert "--db" in plain
    assert "--run" in plain


def test_history_shows_no_runs_when_db_empty(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    result = runner.invoke(app, ["history", "--db", str(db)])
    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_history_shows_table_header(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    result = runner.invoke(app, ["history", "--db", str(db)])
    assert result.exit_code == 0
    assert "Session" in result.output
    assert "Candle Close" in result.output
    assert "SPY" in result.output
    assert "QQQ" in result.output


def test_history_exit_code_2_on_bad_db(tmp_path: Path) -> None:
    bad_db = tmp_path / "bad.db"
    bad_db.write_bytes(b"NOT SQLITE\xff")
    result = runner.invoke(app, ["history", "--db", str(bad_db)])
    assert result.exit_code == 2


def test_history_filter_by_run(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    bank = MemoryBank(str(db))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    result = runner.invoke(app, ["history", "--db", str(db), "--run", "1"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T043: quickstart validation — help commands and config.json.example
# ---------------------------------------------------------------------------


def test_root_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_root_help_lists_run_status_history() -> None:
    result = runner.invoke(app, ["--help"])
    plain = _plain(result.output)
    assert "run" in plain
    assert "status" in plain
    assert "history" in plain


def test_run_help_exits_zero() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0


def test_run_help_lists_expected_options() -> None:
    result = runner.invoke(app, ["run", "--help"])
    plain = _plain(result.output)
    assert "--config" in plain
    assert "--tickers" in plain
    assert "--stop-loss" in plain


def test_config_example_file_loads_without_error(tmp_path: Path) -> None:
    """config.json.example must be valid JSON that passes AlphorynConfig validation."""
    example = Path(__file__).parents[2] / "config.json.example"
    assert example.exists(), "config.json.example is missing from repo root"
    data = json.loads(example.read_text(encoding="utf-8"))
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(data), encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg.tickers == ["SPY", "QQQ"]


def test_memory_bank_default_path_is_home_alphoryn(tmp_path: Path) -> None:
    """status --help reveals that the default --db is ~/.alphoryn/memory.db."""
    result = runner.invoke(app, ["status", "--help"])
    plain = _plain(result.output)
    assert "~/.alphoryn/memory.db" in plain


def test_memory_bank_initializes_at_default_path(tmp_path: Path, monkeypatch) -> None:
    """MemoryBank can be initialised at the default ~/.alphoryn/memory.db path."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    db_path = str((fake_home / ".alphoryn" / "memory.db").expanduser())
    MemoryBank(db_path)
    assert (fake_home / ".alphoryn" / "memory.db").exists()
