"""
Exponential backoff with jitter for external API calls.
NOT applied to trading order placement (risk of double-execution).
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
from collections.abc import Callable
from typing import Any, TypeVar

from config import RETRY_BASE_DELAY_SECONDS, RETRY_MAX_ATTEMPTS, RETRY_MAX_DELAY_SECONDS

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# HTTP status codes that warrant a retry
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def with_retry(func: F) -> F:
    """
    Decorator for async functions that call external APIs.
    Retries on HTTP 429 / 5xx up to RETRY_MAX_ATTEMPTS times with exponential backoff + jitter.
    Do NOT apply to execution.place_* tools.
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                if attempt == RETRY_MAX_ATTEMPTS:
                    break
                delay = _backoff(attempt)
                logger.warning(
                    "retry attempt=%d/%d func=%s delay=%.1fs error=%s",
                    attempt, RETRY_MAX_ATTEMPTS, func.__qualname__, delay, exc,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    return wrapper  # type: ignore[return-value]


def _backoff(attempt: int) -> float:
    base = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
    jitter = random.uniform(0, base * 0.3)
    return min(base + jitter, RETRY_MAX_DELAY_SECONDS)


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    # HTTP status codes in the exception message (works for httpx, alpaca-py, google-genai)
    for code in _RETRYABLE_STATUS:
        if str(code) in msg:
            return True
    # gRPC / Vertex AI status names
    if "resource_exhausted" in msg or "resource exhausted" in msg:
        return True
    # Common exception type names from alpaca-py, httpx, grpc
    retryable_names = {"ratelimiterror", "servererror", "timeouterror", "connectionerror"}
    return type(exc).__name__.lower() in retryable_names
