"""
@log_io decorator — wraps every async tool function to log its input arguments
and output dict at DEBUG level.

Applied in tools/registry.py via the _tool() helper so no individual tool
file needs to be touched.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import time
from collections.abc import Callable
from typing import Any

_logger = logging.getLogger("tools")

_MAX_CHARS = 800


def _serialise(value: object) -> str:
    try:
        raw = json.dumps(value, default=str)
    except Exception:
        raw = repr(value)
    if len(raw) > _MAX_CHARS:
        return raw[:_MAX_CHARS] + " …(truncated)"
    return raw


def log_io(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: log tool name, bound args, result, and elapsed time."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        name = fn.__name__

        # Build a clean {param: value} dict from however the function was called
        try:
            sig = inspect.signature(fn)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            args_repr = _serialise(dict(bound.arguments))
        except Exception:
            args_repr = repr(args) + " " + repr(kwargs)

        _logger.debug("TOOL ▶  %-36s  in  = %s", name, args_repr)

        t0 = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            _logger.error("TOOL ✗  %-36s  [%.0fms]  error = %s", name, elapsed_ms, exc)
            raise

        elapsed_ms = (time.monotonic() - t0) * 1000
        _logger.debug("TOOL ◀  %-36s  [%.0fms]  out = %s", name, elapsed_ms, _serialise(result))
        return result

    return wrapper
