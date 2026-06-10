"""Unit tests for the token bucket rate limiter."""
from __future__ import annotations

import asyncio
import time


def test_token_bucket_acquire_does_not_block_within_burst() -> None:
    from infra.rate_limiter import TokenBucket

    bucket = TokenBucket(rate=100.0, burst=5)

    async def run() -> float:
        start = time.monotonic()
        for _ in range(5):
            await bucket.acquire()
        return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed < 0.5  # 5 tokens within burst, should be near-instant


def test_token_bucket_rate_limits_beyond_burst() -> None:
    from infra.rate_limiter import TokenBucket

    # 10 tokens/sec, burst=2 → 3rd token should wait ~0.1s
    bucket = TokenBucket(rate=10.0, burst=2)

    async def run() -> float:
        start = time.monotonic()
        for _ in range(3):
            await bucket.acquire()
        return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed >= 0.09  # at least one token wait


def test_acquire_alpaca_data_callable() -> None:
    from infra.rate_limiter import acquire_alpaca_data

    # Just verify it runs without error (non-blocking within burst)
    asyncio.run(acquire_alpaca_data())


def test_acquire_yfinance_callable() -> None:
    from infra.rate_limiter import acquire_yfinance

    asyncio.run(acquire_yfinance())
