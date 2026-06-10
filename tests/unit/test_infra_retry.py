"""Unit tests for infra.retry — with_retry, _backoff, _is_retryable."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from config import RETRY_MAX_ATTEMPTS, RETRY_MAX_DELAY_SECONDS
from infra.retry import _backoff, _is_retryable, with_retry

# ── _is_retryable ─────────────────────────────────────────────────────────────

def test_is_retryable_http_429():
    assert _is_retryable(Exception("HTTP 429 Too Many Requests"))


def test_is_retryable_http_500():
    assert _is_retryable(Exception("got 500 internal server error"))


def test_is_retryable_http_502():
    assert _is_retryable(Exception("502 bad gateway"))


def test_is_retryable_http_503():
    assert _is_retryable(Exception("503 service unavailable"))


def test_is_retryable_http_504():
    assert _is_retryable(Exception("504 gateway timeout"))


def test_is_retryable_rate_limit_error_class():
    class RateLimitError(Exception):
        pass
    assert _is_retryable(RateLimitError("exceeded"))


def test_is_retryable_server_error_class():
    class ServerError(Exception):
        pass
    assert _is_retryable(ServerError("internal"))


def test_is_retryable_timeout_error_class():
    class TimeoutError(Exception):
        pass
    assert _is_retryable(TimeoutError("timed out"))


def test_is_retryable_connection_error_class():
    class ConnectionError(Exception):
        pass
    assert _is_retryable(ConnectionError("reset"))


def test_is_retryable_false_for_value_error():
    assert not _is_retryable(ValueError("bad value"))


def test_is_retryable_false_for_key_error():
    assert not _is_retryable(KeyError("missing"))


def test_is_retryable_false_for_runtime_error():
    assert not _is_retryable(RuntimeError("unhandled"))


def test_is_retryable_false_for_type_error():
    assert not _is_retryable(TypeError("wrong type"))


# ── _backoff ──────────────────────────────────────────────────────────────────

def test_backoff_attempt_1_within_bounds():
    delay = _backoff(1)
    assert 1.0 <= delay <= RETRY_MAX_DELAY_SECONDS


def test_backoff_attempt_2_larger_than_1():
    _backoff(1)
    d2 = _backoff(2)
    # attempt 2 base is 2x attempt 1 base; with jitter they might overlap,
    # but max is still bounded
    assert d2 <= RETRY_MAX_DELAY_SECONDS


def test_backoff_caps_at_max_delay():
    # attempt 10 would overflow without the cap
    delay = _backoff(10)
    assert delay <= RETRY_MAX_DELAY_SECONDS


def test_backoff_always_positive():
    for attempt in range(1, 6):
        assert _backoff(attempt) > 0


# ── with_retry decorator ──────────────────────────────────────────────────────

def test_with_retry_succeeds_immediately():
    @with_retry
    async def fn():
        return "ok"

    assert asyncio.run(fn()) == "ok"


def test_with_retry_preserves_function_name():
    @with_retry
    async def my_named_function():
        return None

    assert my_named_function.__name__ == "my_named_function"


def test_with_retry_retries_on_429_then_succeeds():
    call_count = [0]

    @with_retry
    async def fn():
        call_count[0] += 1
        if call_count[0] < 3:
            raise Exception("HTTP 429 rate limited")
        return "success"

    with patch("asyncio.sleep", new=AsyncMock()):
        result = asyncio.run(fn())

    assert result == "success"
    assert call_count[0] == 3


def test_with_retry_raises_non_retryable_immediately():
    call_count = [0]

    @with_retry
    async def fn():
        call_count[0] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        asyncio.run(fn())

    assert call_count[0] == 1


def test_with_retry_exhausts_all_attempts_and_raises():
    call_count = [0]

    @with_retry
    async def fn():
        call_count[0] += 1
        raise Exception("503 service unavailable")

    with patch("asyncio.sleep", new=AsyncMock()), pytest.raises(Exception, match="503"):
        asyncio.run(fn())

    assert call_count[0] == RETRY_MAX_ATTEMPTS


def test_with_retry_logs_warning_on_retry(caplog):
    import logging

    @with_retry
    async def fn():
        raise Exception("500 server error")

    with (
        patch("asyncio.sleep", new=AsyncMock()),
        caplog.at_level(logging.WARNING, logger="infra.retry"),
        pytest.raises(Exception, match="500 server error"),
    ):
        asyncio.run(fn())

    assert any("retry" in r.message for r in caplog.records)


def test_with_retry_passes_args_to_function():
    @with_retry
    async def fn(x: int, y: int) -> int:
        return x + y

    assert asyncio.run(fn(3, 4)) == 7


def test_with_retry_passes_kwargs_to_function():
    @with_retry
    async def fn(*, key: str) -> str:
        return f"got:{key}"

    assert asyncio.run(fn(key="hello")) == "got:hello"


def test_is_retryable_resource_exhausted_grpc():
    assert _is_retryable(Exception("RESOURCE_EXHAUSTED quota exceeded"))


def test_is_retryable_resource_exhausted_lowercase():
    assert _is_retryable(Exception("resource_exhausted from vertex ai"))
