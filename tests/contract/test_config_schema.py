"""Contract tests for the Alphoryn config schema.

Verifies that the AlphorynConfig model + load_config adhere to the
specification in contracts/config-schema.md.
"""

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphoryn.config.loader import load_config
from alphoryn.config.models import AlphorynConfig

# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_tickers_is_required() -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig()  # type: ignore[call-arg]


def test_single_ticker_invalid() -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig(tickers=["SPY"])


# ---------------------------------------------------------------------------
# Optional fields with defaults per contracts/config-schema.md
# ---------------------------------------------------------------------------


def test_candle_timeframe_default_is_one_hour() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.candle_timeframe == "1H"


def test_run_duration_default_is_24_hours() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.run_duration == "24H"


def test_stop_loss_pct_default_is_0_02() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.stop_loss_pct == pytest.approx(0.02)


def test_max_startup_latency_seconds_default_is_60() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.max_startup_latency_seconds == 60


def test_currency_default_is_usd() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.currency == "USD"


def test_memory_db_path_default() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.memory_db_path == "~/.alphoryn/memory.db"


def test_session_money_budget_default_is_none() -> None:
    """null session_money_budget means no limit (contracts/config-schema.md §Field Reference)."""
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.session_money_budget is None


def test_exchange_default_is_none() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.exchange is None


# ---------------------------------------------------------------------------
# session_money_budget = null means no limit
# ---------------------------------------------------------------------------


def test_session_money_budget_none_accepted() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], session_money_budget=None)
    assert cfg.session_money_budget is None


def test_session_money_budget_positive_accepted() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], session_money_budget=1000.0)
    assert cfg.session_money_budget == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# candle_timeframe restricted to 10min | 15min | 30min | 1H | 4H
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tf", ["10min", "15min", "30min", "1H", "4H"])
def test_allowed_candle_timeframes(tf: str) -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], candle_timeframe=tf)
    assert cfg.candle_timeframe == tf


@pytest.mark.parametrize("bad_tf", ["2H", "D", "1h", "30MIN", "1hour", "5min"])
def test_disallowed_candle_timeframes_raise(bad_tf: str) -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig(tickers=["SPY", "QQQ"], candle_timeframe=bad_tf)


# ---------------------------------------------------------------------------
# Fractional session count — warning, not error
# ---------------------------------------------------------------------------


def test_fractional_session_count_rounds_down() -> None:
    """25H / 4H = 6.25 → rounds down to 6. No ValidationError raised."""
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], candle_timeframe="4H", run_duration="25H")
    assert cfg.session_count == math.floor(25 / 4)


def test_non_fractional_session_count() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], candle_timeframe="1H", run_duration="24H")
    assert cfg.session_count == 24


def test_fractional_run_duration_does_not_raise() -> None:
    """Fractional remainder is a warning at runtime, not a config error."""
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], candle_timeframe="4H", run_duration="10H")
    assert isinstance(cfg, AlphorynConfig)


# ---------------------------------------------------------------------------
# stop_loss_pct — range (0, 1) exclusive
# ---------------------------------------------------------------------------


def test_stop_loss_pct_zero_is_invalid() -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig(tickers=["SPY", "QQQ"], stop_loss_pct=0.0)


def test_stop_loss_pct_one_is_invalid() -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig(tickers=["SPY", "QQQ"], stop_loss_pct=1.0)


def test_stop_loss_pct_negative_is_invalid() -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig(tickers=["SPY", "QQQ"], stop_loss_pct=-0.01)


def test_stop_loss_pct_boundary_low_valid() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], stop_loss_pct=0.001)
    assert cfg.stop_loss_pct == pytest.approx(0.001)


def test_stop_loss_pct_boundary_high_valid() -> None:
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], stop_loss_pct=0.20)
    assert cfg.stop_loss_pct == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Alpaca paper mode — always True
# ---------------------------------------------------------------------------


def test_alpaca_paper_mode_is_always_true() -> None:
    """v0.0.1 only supports Alpaca paper trading (contracts/config-schema.md note)."""
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    assert cfg.alpaca_paper_mode is True


# ---------------------------------------------------------------------------
# No secrets in config file
# ---------------------------------------------------------------------------


def test_config_model_has_no_api_key_field() -> None:
    """API keys must not be in the config file (contracts/config-schema.md §GCP Secret Manager)."""
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"])
    fields = set(cfg.model_fields.keys())
    for secret_field in ("api_key", "secret_key", "alpaca_api_key", "alpaca_secret_key"):
        assert secret_field not in fields, f"Secret field {secret_field!r} found in config model"


# ---------------------------------------------------------------------------
# load_config — JSON file + CLI overrides
# ---------------------------------------------------------------------------


def test_load_config_json_fields_all_accepted(tmp_path: Path) -> None:
    payload = {
        "tickers": ["SPY", "QQQ"],
        "candle_timeframe": "4H",
        "run_duration": "8H",
        "session_money_budget": 500.0,
        "stop_loss_pct": 0.03,
        "max_startup_latency_seconds": 120,
        "currency": "USD",
        "memory_db_path": "~/.alphoryn/memory.db",
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(payload), encoding="utf-8")
    cfg = load_config(config_path=cfg_file)
    assert cfg.tickers == ["SPY", "QQQ"]
    assert cfg.candle_timeframe == "4H"
    assert cfg.session_money_budget == pytest.approx(500.0)
    assert cfg.stop_loss_pct == pytest.approx(0.03)


def test_load_config_cli_overrides_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"tickers": ["SPY", "QQQ"]}), encoding="utf-8")
    cfg = load_config(config_path=cfg_file, overrides={"candle_timeframe": "4H"})
    assert cfg.candle_timeframe == "4H"


def test_load_config_none_cli_override_does_not_clobber_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"tickers": ["SPY", "QQQ"], "candle_timeframe": "30min"}),
        encoding="utf-8",
    )
    cfg = load_config(config_path=cfg_file, overrides={"candle_timeframe": None})
    assert cfg.candle_timeframe == "30min"


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    """A missing config with no CLI defaults for required fields raises ValidationError."""
    with pytest.raises(ValidationError):
        load_config(config_path=str(tmp_path / "no_such_file.json"))
