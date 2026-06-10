from __future__ import annotations

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".algotrade"
CONFIG_FILE = CONFIG_DIR / "config.json"
DB_PATH = CONFIG_DIR / "algotrade.db"

# ── ETF universe ─────────────────────────────────────────────────────────────
ETF_UNIVERSES: dict[str, list[str]] = {
    "US_SECTOR_ETFS": [
        "XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
        "SPY", "QQQ", "IWM", "GLD", "TLT", "VNQ",
    ],
    "US_TECH_ETFS": [
        "QQQ", "XLK", "SOXX", "ARKK", "IGV", "SKYY", "WCLD",
    ],
    "US_BROAD_MARKET": [
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",
    ],
    "COMMODITIES": [
        "GLD", "SLV", "USO", "UNG", "DBA", "PDBC",
    ],
    "FIXED_INCOME": [
        "TLT", "IEF", "SHY", "HYG", "LQD", "BND",
    ],
}

DEFAULT_ETF_UNIVERSE: list[str] = ETF_UNIVERSES["US_SECTOR_ETFS"]

# ── Session defaults ──────────────────────────────────────────────────────────
DEFAULT_SHORTLIST_N: int = 2
MAX_SHORTLIST_N: int = 5
DEFAULT_HITL_TIMEOUT_SECONDS: int = 60
DEFAULT_LOSS_LIMIT_EUR: float = 500.0

# ── Calibration ───────────────────────────────────────────────────────────────
DEBATE_TIE_THRESHOLD_PCT: float = 0.5
PESSIMIST_OVERRIDE_WIN_RATE: float = 0.65   # triggers asymmetric HIGH override

# ── Risk synthesis thresholds ─────────────────────────────────────────────────
RISK_LOW_THRESHOLD: float = 0.6
RISK_HIGH_THRESHOLD: float = 1.2

# ── Context management ────────────────────────────────────────────────────────
CONTEXT_HEADROOM_MIN_PCT: float = 0.25      # compact if free context < 25%

# ── Rate limits ───────────────────────────────────────────────────────────────
RATE_ALPACA_DATA_PER_MIN: int = 200
RATE_ALPACA_DATA_BURST: int = 10
RATE_ALPACA_TRADING_PER_MIN: int = 10
RATE_ALPACA_TRADING_BURST: int = 3
RATE_YFINANCE_PER_SEC: float = 2.0
RATE_YFINANCE_BURST: int = 3
RATE_SECRET_MANAGER_PER_MIN: int = 10
RATE_SECRET_MANAGER_BURST: int = 2

# ── Retry ─────────────────────────────────────────────────────────────────────
RETRY_MAX_ATTEMPTS: int = 3
RETRY_BASE_DELAY_SECONDS: float = 1.0
RETRY_MAX_DELAY_SECONDS: float = 30.0

# ── Signal lookback ───────────────────────────────────────────────────────────
SIGNAL_LOOKBACK_BARS: int = 90
SIGNAL_FORWARD_RETURN_DAYS: int = 3

# ── Outcome resolution ────────────────────────────────────────────────────────
OUTCOME_CUTOFF_EXTRA_DAYS: int = 1          # timeframe + 1 day before marking timed_out

# ── GCP ───────────────────────────────────────────────────────────────────────
GCP_PROJECT_ID_ENV: str = "GOOGLE_CLOUD_PROJECT"
ALPACA_API_KEY_SECRET: str = "alpaca-api-key"
ALPACA_API_SECRET_SECRET: str = "alpaca-api-secret"
