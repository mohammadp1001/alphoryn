"""
Token-bucket rate limiters — one per external API.
Thread-safe for async use via asyncio.Lock.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from config import (
    RATE_ALPACA_DATA_BURST,
    RATE_ALPACA_DATA_PER_MIN,
    RATE_ALPACA_TRADING_BURST,
    RATE_ALPACA_TRADING_PER_MIN,
    RATE_GEMINI_BURST,
    RATE_GEMINI_PER_MIN,
    RATE_SECRET_MANAGER_BURST,
    RATE_SECRET_MANAGER_PER_MIN,
    RATE_YFINANCE_BURST,
    RATE_YFINANCE_PER_SEC,
)


@dataclass
class TokenBucket:
    rate: float         # tokens added per second
    burst: int          # max tokens (bucket capacity)
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()

    async def acquire(self, tokens: int = 1) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._last_refill = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                wait = (tokens - self._tokens) / self.rate
                await asyncio.sleep(wait)


# ── Singleton limiters (created lazily per event loop) ────────────────────────

_limiters: dict[str, TokenBucket] = {}


def _get(name: str) -> TokenBucket:
    if name not in _limiters:
        cfg = _CONFIGS[name]
        _limiters[name] = TokenBucket(**cfg)
    return _limiters[name]


_CONFIGS: dict[str, dict] = {
    "alpaca_data": {
        "rate": RATE_ALPACA_DATA_PER_MIN / 60,
        "burst": RATE_ALPACA_DATA_BURST,
    },
    "alpaca_trading": {
        "rate": RATE_ALPACA_TRADING_PER_MIN / 60,
        "burst": RATE_ALPACA_TRADING_BURST,
    },
    "yfinance": {
        "rate": RATE_YFINANCE_PER_SEC,
        "burst": RATE_YFINANCE_BURST,
    },
    "secret_manager": {
        "rate": RATE_SECRET_MANAGER_PER_MIN / 60,
        "burst": RATE_SECRET_MANAGER_BURST,
    },
    "gemini": {
        "rate": RATE_GEMINI_PER_MIN / 60,
        "burst": RATE_GEMINI_BURST,
    },
}


async def acquire_alpaca_data() -> None:
    await _get("alpaca_data").acquire()


async def acquire_alpaca_trading() -> None:
    await _get("alpaca_trading").acquire()


async def acquire_yfinance() -> None:
    await _get("yfinance").acquire()


async def acquire_secret_manager() -> None:
    await _get("secret_manager").acquire()


async def acquire_gemini() -> None:
    await _get("gemini").acquire()
