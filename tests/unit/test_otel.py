"""Unit tests for alphoryn/telemetry/otel.py."""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from alphoryn.telemetry.otel import _add_gcp_project_resource_attribute, setup_otel


@pytest.fixture(autouse=True)
def _mock_google_auth_default():
    target = "alphoryn.telemetry.otel.google.auth.default"
    with patch(target, return_value=(MagicMock(), "test-project")) as m:
        yield m


def _patched_otel(mock_get=None, mock_set=None):
    """Context manager that patches both module-level ADK callables."""
    if mock_get is None:
        mock_get = MagicMock()
    if mock_set is None:
        mock_set = MagicMock()
    return (
        patch("alphoryn.telemetry.otel._get_gcp_exporters", mock_get),
        patch("alphoryn.telemetry.otel._maybe_set_otel_providers", mock_set),
    )


def test_setup_otel_sets_service_name_env_var(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    assert os.environ["OTEL_SERVICE_NAME"] == "alphoryn"


def test_setup_otel_does_not_override_existing_service_name(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SERVICE_NAME", "my-custom-name")
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    assert os.environ["OTEL_SERVICE_NAME"] == "my-custom-name"


def test_setup_otel_enables_genai_content_capture_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "true"


def test_setup_otel_does_not_override_content_capture_if_set(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "false"


def test_setup_otel_calls_get_gcp_exporters_with_tracing_and_logging(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    mock_get = MagicMock()
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2:
        setup_otel()
    mock_get.assert_called_once_with(enable_cloud_tracing=True, enable_cloud_logging=True)


def test_setup_otel_sets_project_id_resource_attribute(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == "gcp.project_id=test-project"


def test_setup_otel_skips_resource_attribute_when_project_id_is_none(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    p1, p2 = _patched_otel()
    target = "alphoryn.telemetry.otel.google.auth.default"
    with p1, p2, patch(target, return_value=(MagicMock(), None)):
        setup_otel()
    assert "OTEL_RESOURCE_ATTRIBUTES" not in os.environ


def test_setup_otel_passes_exporters_to_maybe_set(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    mock_exporters = MagicMock()
    mock_get = MagicMock(return_value=mock_exporters)
    mock_set = MagicMock()
    p1, p2 = _patched_otel(mock_get=mock_get, mock_set=mock_set)
    with p1, p2:
        setup_otel()
    mock_set.assert_called_once_with([mock_exporters])


def test_setup_otel_does_not_raise_on_runtime_error(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    mock_get = MagicMock(side_effect=RuntimeError("gcp error"))
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2:
        setup_otel()  # must not raise


def test_setup_otel_logs_warning_on_failure(monkeypatch, caplog) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    mock_get = MagicMock(side_effect=RuntimeError("gcp error"))
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2, caplog.at_level(logging.WARNING, logger="alphoryn.telemetry.otel"):
        setup_otel()
    assert any("OpenTelemetry setup failed" in r.message for r in caplog.records)


def test_setup_otel_does_not_raise_on_import_error(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    mock_get = MagicMock(side_effect=ImportError("opentelemetry-exporter-gcp-trace not installed"))
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2:
        setup_otel()  # must not raise even if exporter packages are missing


def test_setup_otel_logs_warning_on_import_error(monkeypatch, caplog) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    mock_get = MagicMock(side_effect=ImportError("opentelemetry-exporter-gcp-trace not installed"))
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2, caplog.at_level(logging.WARNING, logger="alphoryn.telemetry.otel"):
        setup_otel()
    assert any("OpenTelemetry setup failed" in r.message for r in caplog.records)


def test_setup_otel_does_not_raise_when_google_auth_default_fails(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    p1, p2 = _patched_otel()
    target = "alphoryn.telemetry.otel.google.auth.default"
    with p1, p2, patch(target, side_effect=RuntimeError("no credentials")):
        setup_otel()  # must not raise


def test_add_gcp_project_resource_attribute_sets_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    _add_gcp_project_resource_attribute("test-project")
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == "gcp.project_id=test-project"


def test_add_gcp_project_resource_attribute_merges_with_existing(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=custom")
    _add_gcp_project_resource_attribute("test-project")
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == "service.name=custom,gcp.project_id=test-project"


def test_add_gcp_project_resource_attribute_noop_if_already_present(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "gcp.project_id=already-set")
    _add_gcp_project_resource_attribute("test-project")
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == "gcp.project_id=already-set"
