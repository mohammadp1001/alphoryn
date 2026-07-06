import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphoryn.config.loader import load_config
from alphoryn.config.models import AlphorynConfig, _parse_duration_seconds

# ---------------------------------------------------------------------------
# _parse_duration_seconds
# ---------------------------------------------------------------------------


def test_parse_duration_seconds_hours() -> None:
    assert _parse_duration_seconds("24H") == 86400


def test_parse_duration_seconds_minutes() -> None:
    assert _parse_duration_seconds("30MIN") == 1800


def test_parse_duration_seconds_whitespace() -> None:
    assert _parse_duration_seconds("  4H  ") == 14400


def test_parse_duration_seconds_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported duration format"):
        _parse_duration_seconds("10D")


# ---------------------------------------------------------------------------
# AlphorynConfig — required fields
# ---------------------------------------------------------------------------


def test_config_missing_etf1_raises() -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig(etf2="QQQ")  # type: ignore[call-arg]


def test_config_missing_etf2_raises() -> None:
    with pytest.raises(ValidationError):
        AlphorynConfig(etf1="SPY")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# AlphorynConfig — defaults
# ---------------------------------------------------------------------------


def _minimal(**extra) -> AlphorynConfig:
    return AlphorynConfig(etf1="SPY", etf2="QQQ", **extra)


def test_config_defaults() -> None:
    cfg = _minimal()
    assert cfg.candle_timeframe == "1H"
    assert cfg.run_duration == "24H"
    assert cfg.currency == "USD"
    assert cfg.stop_loss_pct == pytest.approx(0.02)
    assert cfg.max_startup_latency_seconds == 60
    assert cfg.memory_db_path == "~/.alphoryn/memory.db"
    assert cfg.session_money_budget is None
    assert cfg.exchange is None


# ---------------------------------------------------------------------------
# AlphorynConfig — field validation
# ---------------------------------------------------------------------------


def test_config_invalid_candle_timeframe_raises() -> None:
    with pytest.raises(ValidationError):
        _minimal(candle_timeframe="15min")


def test_config_valid_candle_timeframes() -> None:
    for tf in ("30min", "1H", "4H"):
        cfg = _minimal(candle_timeframe=tf)
        assert cfg.candle_timeframe == tf


def test_config_stop_loss_pct_zero_raises() -> None:
    with pytest.raises(ValidationError, match="stop_loss_pct"):
        _minimal(stop_loss_pct=0.0)


def test_config_stop_loss_pct_one_raises() -> None:
    with pytest.raises(ValidationError, match="stop_loss_pct"):
        _minimal(stop_loss_pct=1.0)


def test_config_stop_loss_pct_negative_raises() -> None:
    with pytest.raises(ValidationError):
        _minimal(stop_loss_pct=-0.01)


def test_config_stop_loss_pct_valid() -> None:
    cfg = _minimal(stop_loss_pct=0.05)
    assert cfg.stop_loss_pct == pytest.approx(0.05)


def test_config_invalid_run_duration_raises() -> None:
    with pytest.raises(ValidationError):
        _minimal(run_duration="5D")


def test_config_run_duration_minutes_valid() -> None:
    cfg = _minimal(candle_timeframe="30min", run_duration="30MIN")
    assert cfg.run_duration == "30MIN"


# ---------------------------------------------------------------------------
# AlphorynConfig — derived properties
# ---------------------------------------------------------------------------


def test_session_count_24h_1h() -> None:
    cfg = _minimal(candle_timeframe="1H", run_duration="24H")
    assert cfg.session_count == 24


def test_session_count_24h_4h() -> None:
    cfg = _minimal(candle_timeframe="4H", run_duration="24H")
    assert cfg.session_count == 6


def test_session_count_30min_candle() -> None:
    cfg = _minimal(candle_timeframe="30min", run_duration="24H")
    assert cfg.session_count == 48


def test_session_count_floor_division() -> None:
    # 25H run / 4H candle → floor(25/4) = 6
    cfg = _minimal(candle_timeframe="4H", run_duration="25H")
    assert cfg.session_count == math.floor(25 / 4)


def test_alpaca_paper_mode_always_true() -> None:
    assert _minimal().alpaca_paper_mode is True


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_from_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"etf1": "SPY", "etf2": "QQQ", "stop_loss_pct": 0.03}),
        encoding="utf-8",
    )
    cfg = load_config(config_path=cfg_file)
    assert cfg.etf1 == "SPY"
    assert cfg.etf2 == "QQQ"
    assert cfg.stop_loss_pct == pytest.approx(0.03)


def test_load_config_missing_file_uses_empty_dict() -> None:
    # A missing file path should raise because etf1/etf2 are required
    with pytest.raises(ValidationError):
        load_config(config_path="/nonexistent/path/config.json")


def test_load_config_cli_overrides_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"etf1": "SPY", "etf2": "QQQ", "stop_loss_pct": 0.03}),
        encoding="utf-8",
    )
    cfg = load_config(config_path=cfg_file, overrides={"stop_loss_pct": 0.05})
    assert cfg.stop_loss_pct == pytest.approx(0.05)


def test_load_config_none_overrides_not_applied(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"etf1": "SPY", "etf2": "QQQ", "stop_loss_pct": 0.03}),
        encoding="utf-8",
    )
    cfg = load_config(config_path=cfg_file, overrides={"stop_loss_pct": None})
    # None value must NOT override the file value
    assert cfg.stop_loss_pct == pytest.approx(0.03)


def test_load_config_no_file_no_overrides_raises() -> None:
    with pytest.raises(ValidationError):
        load_config(config_path="/nonexistent/config.json", overrides=None)


def test_load_config_invalid_json_raises(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_config(config_path=cfg_file)


def test_load_config_override_candle_timeframe(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"etf1": "SPY", "etf2": "QQQ"}),
        encoding="utf-8",
    )
    cfg = load_config(config_path=cfg_file, overrides={"candle_timeframe": "4H"})
    assert cfg.candle_timeframe == "4H"
