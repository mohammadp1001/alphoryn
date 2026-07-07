"""Unit tests for alphoryn/telemetry/otel.py."""

import logging
import os
from unittest.mock import MagicMock, patch

from alphoryn.telemetry.otel import setup_otel


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


def test_setup_otel_calls_get_gcp_exporters_with_cloud_logging(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    mock_get = MagicMock()
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2:
        setup_otel()
    mock_get.assert_called_once_with(enable_cloud_logging=True)


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
