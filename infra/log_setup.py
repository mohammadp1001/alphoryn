"""
Force-configure a stderr console logger that works regardless of what ADK or
other libraries have already attached to the root logger.

Call configure_console_logging() once at process start, before any ADK imports.
"""
from __future__ import annotations

import logging
import sys


def configure_console_logging(level: int = logging.DEBUG) -> None:
    """Clear all existing root-logger handlers and attach a fresh stderr StreamHandler.

    logging.basicConfig() is a no-op when any handler is already configured
    (which ADK does on import).  This function forces the setup regardless.
    """
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)-32s %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Suppress high-volume third-party noise at WARNING+
    _quiet = (
        "urllib3", "httpcore", "httpx", "asyncio", "grpc",
        "google.auth", "google.api_core", "opentelemetry",
        "werkzeug", "charset_normalizer",
    )
    for name in _quiet:
        logging.getLogger(name).setLevel(logging.WARNING)
