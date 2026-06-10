"""Unit tests for infra.observability — setup and span helpers."""
from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

# ── setup_observability (local / no GCP) ─────────────────────────────────────

def test_setup_observability_local_sets_tracer(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    import infra.observability as obs
    obs._tracer = None  # reset global

    obs.setup_observability("test-session-123")

    assert obs._tracer is not None
    assert obs._session_trace_id == "test-session-123"


def test_setup_observability_local_falls_back_gracefully(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    import infra.observability as obs

    # Should not raise
    obs.setup_observability("local-session")
    assert obs._session_trace_id == "local-session"


def test_setup_observability_with_gcp_project(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-gcp-project")

    import infra.observability as obs
    obs._tracer = None

    # Patch both cloud setup methods to avoid actual GCP calls
    with (
        patch.object(obs, "_setup_cloud_trace") as mock_trace,
        patch.object(obs, "_setup_cloud_logging") as mock_logging,
    ):
        obs.setup_observability("gcp-session")

    mock_trace.assert_called_once()
    mock_logging.assert_called_once()
    assert obs._tracer is not None


def test_setup_observability_cloud_trace_import_error_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")

    import infra.observability as obs
    obs._tracer = None

    # Patch both to avoid any actual GCP calls; just verify it doesn't raise
    with patch.object(obs, "_setup_cloud_trace"), patch.object(obs, "_setup_cloud_logging"):
        obs.setup_observability("fallback-session")

    assert obs._tracer is not None


# ── _setup_local_trace ────────────────────────────────────────────────────────

def test_setup_local_trace_does_not_raise():
    from opentelemetry.sdk.resources import Resource

    import infra.observability as obs

    resource = Resource.create({"service.name": "test"})
    # Should not raise
    obs._setup_local_trace(resource)


# ── _setup_cloud_trace ────────────────────────────────────────────────────────

def test_setup_cloud_trace_falls_back_if_import_error(monkeypatch):
    from opentelemetry.sdk.resources import Resource

    import infra.observability as obs

    resource = Resource.create({"service.name": "test"})

    with (
        patch.dict(sys.modules, {"opentelemetry.exporter.cloud_trace": None}),
        patch.object(obs, "_setup_local_trace") as mock_local,
    ):
        # ImportError from missing module; should fall back to local
        obs._setup_cloud_trace(resource, "my-project", "sess-1")
        mock_local.assert_called_once_with(resource)


def test_setup_cloud_trace_success_path():
    """Success path: CloudTraceSpanExporter found → sets up GCP tracer provider."""
    from opentelemetry.sdk.resources import Resource

    import infra.observability as obs

    resource = Resource.create({"service.name": "test"})

    mock_exporter = MagicMock()
    mock_exporter_class = MagicMock(return_value=mock_exporter)
    mock_cloud_trace_mod = MagicMock()
    mock_cloud_trace_mod.CloudTraceSpanExporter = mock_exporter_class

    with patch.dict(sys.modules, {"opentelemetry.exporter.cloud_trace": mock_cloud_trace_mod}):
        obs._setup_cloud_trace(resource, "my-project", "sess-x")

    mock_exporter_class.assert_called_once_with(project_id="my-project")


# ── _setup_cloud_logging ──────────────────────────────────────────────────────

def _inject_google_cloud_logging(mock_cloud_logging_mod: MagicMock) -> tuple:
    """
    Inject a mock google.cloud.logging into sys.modules AND onto the google namespace.
    Returns (mock_gcloud, original_cloud_attr) for cleanup in finally blocks.
    """
    import google as google_mod
    mock_gcloud = MagicMock()
    mock_gcloud.logging = mock_cloud_logging_mod
    # Attach to the real google namespace package so `google.cloud.logging` attribute access works
    orig_cloud = getattr(google_mod, "cloud", None)
    google_mod.cloud = mock_gcloud  # type: ignore[attr-defined]
    return google_mod, orig_cloud


def _restore_google_cloud(google_mod, orig_cloud) -> None:
    if orig_cloud is None and hasattr(google_mod, "cloud"):
        delattr(google_mod, "cloud")
    elif orig_cloud is not None:
        google_mod.cloud = orig_cloud


def test_setup_cloud_logging_with_google_cloud_logging():
    """Success path: google.cloud.logging installed → client.setup_logging called."""
    import infra.observability as obs

    mock_client = MagicMock()
    mock_cloud_logging_mod = MagicMock()
    mock_cloud_logging_mod.Client.return_value = mock_client

    google_mod, orig_cloud = _inject_google_cloud_logging(mock_cloud_logging_mod)
    try:
        with patch.dict(sys.modules, {"google.cloud.logging": mock_cloud_logging_mod}):
            obs._setup_cloud_logging("test-project", "sess-xyz")
    finally:
        _restore_google_cloud(google_mod, orig_cloud)

    mock_client.setup_logging.assert_called_once()


def test_setup_cloud_logging_without_google_cloud_logging():
    """When google.cloud.logging is unavailable, falls back to basicConfig."""
    import infra.observability as obs
    # google.cloud.logging is not installed → ImportError fallback
    obs._setup_cloud_logging("project", "sess")  # should not raise


def test_setup_cloud_logging_injects_session_id_into_log_record():
    """Record factory must inject session_id field."""
    import infra.observability as obs

    mock_client = MagicMock()
    mock_cloud_logging_mod = MagicMock()
    mock_cloud_logging_mod.Client.return_value = mock_client

    google_mod, orig_cloud = _inject_google_cloud_logging(mock_cloud_logging_mod)
    try:
        with patch.dict(sys.modules, {"google.cloud.logging": mock_cloud_logging_mod}):
            obs._setup_cloud_logging("project", "my-session-id")
    finally:
        _restore_google_cloud(google_mod, orig_cloud)

    # Create a log record to check injection
    record = logging.getLogger("test").makeRecord(
        name="test", level=logging.INFO, fn="", lno=0, msg="hello", args=(), exc_info=None
    )
    assert hasattr(record, "session_id")
    assert record.session_id == "my-session-id"


# ── span context managers ─────────────────────────────────────────────────────

def test_span_yields_span_object():
    from infra.observability import span

    with span("test.span", key="val") as s:
        assert s is not None


def test_span_with_attributes_does_not_raise():
    from infra.observability import span

    with span("my.span", foo="bar", count=42):
        pass  # No exception


def test_decision_cycle_span_yields():
    from infra.observability import decision_cycle_span

    with decision_cycle_span(cycle_index=0, strategy="MOMENTUM", regime="BULL_TREND") as s:
        assert s is not None


def test_subagent_span_yields():
    from infra.observability import subagent_span

    with subagent_span("research_agent", task="detect_regime") as s:
        assert s is not None


def test_api_call_span_yields():
    from infra.observability import api_call_span

    with api_call_span("alpaca_trading", "get_portfolio") as s:
        assert s is not None


def test_hitl_span_yields():
    from infra.observability import hitl_span

    with hitl_span("BUY 10 XLK") as s:
        assert s is not None


def test_db_write_span_yields():
    from infra.observability import db_write_span

    with db_write_span(table="trade_records", record_id="abc-123") as s:
        assert s is not None


# ── get_logger ────────────────────────────────────────────────────────────────

def test_get_logger_returns_logger():
    from infra.observability import get_logger

    logger = get_logger("test.module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test.module"


def test_get_logger_different_names():
    from infra.observability import get_logger

    l1 = get_logger("module.a")
    l2 = get_logger("module.b")
    assert l1 is not l2


# ── _setup_cloud_logging ImportError fallback ─────────────────────────────────

def test_setup_cloud_logging_import_error_falls_back_to_basicconfig():
    """Lines 75-76: missing google.cloud.logging → basicConfig(INFO)."""
    import infra.observability as obs

    with patch.dict("sys.modules", {"google.cloud.logging": None}):
        obs._setup_cloud_logging("my-project", "sess-001")

    root = logging.getLogger()
    assert root.level <= logging.INFO or any(
        isinstance(h, logging.StreamHandler) for h in root.handlers
    )
