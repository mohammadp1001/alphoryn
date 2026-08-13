import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

import google.cloud.logging as _gcloud_logging

_logger = logging.getLogger(__name__)

EVENT_TYPES = frozenset(
    {
        "AGENT_DECISION",
        "TOOL_CALL",
        "SIGNAL_SNAPSHOT_BUILT",
        "ORDER_PLACED",
        "ORDER_FAILED",
        "BUDGET_CHECK",
        "STOP_LOSS_TRIGGERED",
        "PROFIT_TARGET_TRIGGERED",
        "WINDOW_EXPIRY_TRIGGERED",
        "POSITION_CLOSED",
        "SESSION_START",
        "SESSION_END",
        "MARKET_CLOSED",
        "BUDGET_TIMEOUT",
        "TICKER_BLOCKED",
        "MONITOR_STARTED",
        "MONITOR_STOPPED",
        "MONITOR_ERROR",
        "EVALUATION_FAILED",
        "RECONCILE_MISMATCH",
        "RECONCILE_RESOLVED",
        "RECONCILE_FAILED",
        "TOKEN_USAGE",
        "POSITIONS_ABANDONED",
    }
)


class TelemetryLogger:
    """System-wide structured event emitter.

    Emits typed JSON events to GCP Cloud Logging. If Cloud Logging is
    unavailable, events fall back to stderr. Per constitution Principle IV,
    a logging failure NEVER blocks or aborts execution.
    """

    def __init__(self, log_name: str = "alphoryn") -> None:
        self._log_name = log_name
        self._cloud_logger: object | None = None
        try:
            client = _gcloud_logging.Client()
            self._cloud_logger = client.logger(log_name)
        except Exception as exc:
            _logger.warning("Cloud Logging unavailable, falling back to stderr: %s", exc)

    def emit(
        self,
        event_type: str,
        component: str,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
        etf: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Emit a structured event to Cloud Logging (or stderr on failure).

        Args:
            event_type: One of the defined event types (see EVENT_TYPES).
            component:  Emitting component (e.g. ``"main_agent"``, ``"monitor"``).
            payload:    Event-specific fields.
            session_id: Parent session ID (``run-N/session-X``); None for run-level.
            etf:        Ticker symbol where applicable (kept as ``etf`` for log schema
                        stability — renaming would break existing log queries).
            latency_ms: Duration in milliseconds where applicable.
        """
        if event_type not in EVENT_TYPES:
            # Warn, never block (Principle IV). Undeclared event types are drift:
            # EVALUATION_FAILED, MONITOR_STARTED and MONITOR_STOPPED were each
            # emitted for several releases without ever being declared here.
            _logger.warning("Emitting undeclared event type %r; add it to EVENT_TYPES", event_type)
        event: dict[str, Any] = {
            "event_type": event_type,
            "session_id": session_id,
            "component": component,
            "etf": etf,
            "timestamp": datetime.now(UTC).isoformat(),
            "latency_ms": latency_ms,
            "payload": payload,
        }
        if self._cloud_logger is not None:
            try:
                self._cloud_logger.log_struct(event)  # type: ignore[union-attr]
                return
            except Exception as exc:
                _logger.warning("Cloud Logging write failed, falling back to stderr: %s", exc)
        # Fallback: write to stderr (constitution Principle IV)
        print(json.dumps(event, default=str), file=sys.stderr)  # noqa: T201
