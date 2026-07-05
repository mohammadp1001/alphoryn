import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from alphoryn.telemetry.logger import EVENT_TYPES, TelemetryLogger


# ---------------------------------------------------------------------------
# EVENT_TYPES constant
# ---------------------------------------------------------------------------


def test_event_types_contains_all_14() -> None:
    assert len(EVENT_TYPES) == 14


def test_event_types_includes_expected_values() -> None:
    expected = {
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
    }
    assert EVENT_TYPES == expected


# ---------------------------------------------------------------------------
# TelemetryLogger — construction
# ---------------------------------------------------------------------------


def _make_logger_no_cloud() -> TelemetryLogger:
    """Build a TelemetryLogger with Cloud Logging unavailable (stderr fallback)."""
    with patch.dict(
        "sys.modules",
        {"google.cloud.logging": None, "google": None, "google.cloud": None},
    ):
        return TelemetryLogger()


def _make_logger_with_cloud() -> tuple[TelemetryLogger, MagicMock]:
    """Build a TelemetryLogger backed by a mock Cloud Logging client.

    After `import google.cloud.logging` (a statement), the local name `google`
    is bound to sys.modules["google"]. All subsequent attribute accesses
    (google.cloud.logging.Client) therefore traverse the MagicMock chain
    attached to that entry, not sys.modules["google.cloud.logging"] directly.
    So we wire the full attribute path on mock_google.
    """
    mock_cloud_logger = MagicMock()
    mock_client_instance = MagicMock()
    mock_client_instance.logger.return_value = mock_cloud_logger
    mock_gcl = MagicMock()
    mock_gcl.Client.return_value = mock_client_instance
    mock_google_cloud = MagicMock()
    mock_google_cloud.logging = mock_gcl
    mock_google = MagicMock()
    mock_google.cloud = mock_google_cloud

    with patch.dict(
        "sys.modules",
        {
            "google": mock_google,
            "google.cloud": mock_google_cloud,
            "google.cloud.logging": mock_gcl,
        },
    ):
        logger = TelemetryLogger(log_name="test-log")

    return logger, mock_cloud_logger


def test_logger_init_without_cloud_logging() -> None:
    logger = _make_logger_no_cloud()
    assert logger._cloud_logger is None  # type: ignore[attr-defined]


def test_logger_init_with_cloud_logging() -> None:
    logger, mock_cloud_logger = _make_logger_with_cloud()
    assert logger._cloud_logger is mock_cloud_logger  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TelemetryLogger.emit — stderr fallback
# ---------------------------------------------------------------------------


def _emit_to_stderr(event_type: str, **kwargs) -> dict:  # type: ignore[no-untyped-def]
    """Emit one event via the stderr-fallback logger and return the parsed JSON."""
    logger = _make_logger_no_cloud()
    buf = StringIO()
    with patch("sys.stderr", buf):
        logger.emit(event_type, "test_component", {"key": "val"}, **kwargs)
    return json.loads(buf.getvalue())


@pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
def test_all_14_event_types_emit_correct_schema(event_type: str) -> None:
    event = _emit_to_stderr(event_type, session_id="run-1/session-a1b2", etf="SPY", latency_ms=42)
    assert event["event_type"] == event_type
    assert event["session_id"] == "run-1/session-a1b2"
    assert event["etf"] == "SPY"
    assert event["latency_ms"] == 42
    assert event["component"] == "test_component"
    assert "timestamp" in event
    assert "payload" in event


def test_emit_session_id_present_on_every_event() -> None:
    event = _emit_to_stderr("ORDER_PLACED", session_id="run-2/session-xyz")
    assert event["session_id"] == "run-2/session-xyz"


def test_emit_latency_ms_present_on_every_event() -> None:
    event = _emit_to_stderr("SESSION_START", latency_ms=123)
    assert event["latency_ms"] == 123


def test_emit_optional_fields_none_when_not_provided() -> None:
    event = _emit_to_stderr("BUDGET_CHECK")
    assert event["session_id"] is None
    assert event["etf"] is None
    assert event["latency_ms"] is None


def test_emit_payload_forwarded() -> None:
    logger = _make_logger_no_cloud()
    buf = StringIO()
    with patch("sys.stderr", buf):
        logger.emit("TOOL_CALL", "agent", {"tool": "build_snapshot", "args": {"etf": "QQQ"}})
    event = json.loads(buf.getvalue())
    assert event["payload"]["tool"] == "build_snapshot"


# ---------------------------------------------------------------------------
# TelemetryLogger.emit — Cloud Logging path
# ---------------------------------------------------------------------------


def test_emit_uses_cloud_logger_when_available() -> None:
    logger, mock_cloud_logger = _make_logger_with_cloud()
    logger.emit("SESSION_START", "coordinator", {})
    mock_cloud_logger.log_struct.assert_called_once()
    call_args = mock_cloud_logger.log_struct.call_args[0][0]
    assert call_args["event_type"] == "SESSION_START"


def test_cloud_logging_failure_falls_back_to_stderr() -> None:
    logger, mock_cloud_logger = _make_logger_with_cloud()
    mock_cloud_logger.log_struct.side_effect = RuntimeError("quota exceeded")

    buf = StringIO()
    with patch("sys.stderr", buf):
        logger.emit("ORDER_FAILED", "monitor", {"reason": "api_error"})

    # Execution must NOT be blocked
    event = json.loads(buf.getvalue())
    assert event["event_type"] == "ORDER_FAILED"


def test_cloud_logging_failure_does_not_raise() -> None:
    logger, mock_cloud_logger = _make_logger_with_cloud()
    mock_cloud_logger.log_struct.side_effect = RuntimeError("timeout")

    # Must not raise — constitution Principle IV
    logger.emit("BUDGET_TIMEOUT", "scheduler", {})


def test_emit_cloud_success_does_not_write_stderr() -> None:
    logger, mock_cloud_logger = _make_logger_with_cloud()
    mock_cloud_logger.log_struct.return_value = None  # success

    buf = StringIO()
    with patch("sys.stderr", buf):
        logger.emit("SESSION_END", "coordinator", {})

    assert buf.getvalue() == ""
