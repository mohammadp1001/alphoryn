import logging
import math
from typing import Literal

from pydantic import BaseModel, field_validator

_logger = logging.getLogger(__name__)

_TIMEFRAME_SECONDS: dict[str, int] = {
    "10min": 600,
    "15min": 900,
    "30min": 1800,
    "1H": 3600,
    "4H": 14400,
}


def _parse_duration_seconds(value: str) -> int:
    """Parse a duration string (e.g. '24H', '8H') into total seconds."""
    v = value.strip().upper()
    if v.endswith("H"):
        return int(v[:-1]) * 3600
    if v.endswith("MIN"):
        return int(v[:-3]) * 60
    _logger.error("Unsupported duration format: %r — expected e.g. '24H' or '30MIN'", value)
    raise ValueError(f"Unsupported duration format: {value!r}. Expected e.g. '24H' or '30MIN'.")


class AlphorynConfig(BaseModel):
    """Single source of truth for all session parameters.

    Loaded from a JSON config file with optional CLI overrides.
    Passed to all components; no global config state.
    """

    tickers: list[str]
    candle_timeframe: Literal["10min", "15min", "30min", "1H", "4H"] = "1H"
    extended_hours: bool = False
    run_duration: str = "24H"
    exchange: str | None = None
    session_money_budget: float | None = None
    stop_loss_pct: float = 0.02
    max_startup_latency_seconds: int = 60
    currency: str = "USD"
    memory_db_path: str = "~/.alphoryn/memory.db"

    @field_validator("tickers")
    @classmethod
    def validate_tickers(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("tickers must contain at least 2 symbols")
        return v

    @field_validator("stop_loss_pct")
    @classmethod
    def validate_stop_loss_pct(cls, v: float) -> float:
        if not 0 < v < 1:
            _logger.error("Invalid stop_loss_pct=%s — must be between 0 and 1 exclusive", v)
            raise ValueError(f"stop_loss_pct must be between 0 and 1 exclusive, got {v}")
        return v

    @field_validator("run_duration")
    @classmethod
    def validate_run_duration(cls, v: str) -> str:
        _parse_duration_seconds(v)
        return v

    @property
    def session_count(self) -> int:
        """Derived session count: floor(run_duration / candle_timeframe)."""
        run_secs = _parse_duration_seconds(self.run_duration)
        candle_secs = _TIMEFRAME_SECONDS[self.candle_timeframe]
        return math.floor(run_secs / candle_secs)

    @property
    def alpaca_paper_mode(self) -> bool:
        """Always True for v0.0.1 — paper trading only."""
        return True
