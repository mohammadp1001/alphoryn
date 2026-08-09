"""Unit tests for alphoryn/telemetry/otel.py."""

import os
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider

from alphoryn.telemetry.otel import (
    TelemetrySetupError,
    _add_gcp_project_resource_attribute,
    _enable_experimental_genai_semconv,
    _verify_tracer_provider_installed,
    flush_otel,
    setup_otel,
)


@pytest.fixture(autouse=True)
def _mock_google_auth_default():
    target = "alphoryn.telemetry.otel.google.auth.default"
    with patch(target, return_value=(MagicMock(), "test-project")) as m:
        yield m


@pytest.fixture(autouse=True)
def _installed_tracer_provider():
    """Stand in for the TracerProvider ADK would have installed.

    _maybe_set_otel_providers is mocked out in these tests, so nothing ever
    reaches the real global provider; without this the post-setup verification
    would fail in every test for the wrong reason.
    """
    provider = TracerProvider()
    with patch("alphoryn.telemetry.otel.trace.get_tracer_provider", return_value=provider) as m:
        yield m


@pytest.fixture(autouse=True)
def _no_real_atexit_registration():
    """Keep flush_otel out of the real atexit table across the whole suite."""
    with patch("alphoryn.telemetry.otel.atexit.register") as m:
        yield m


def _patched_otel(mock_get=None, mock_set=None):
    """Context manager pair that patches both module-level ADK callables."""
    if mock_get is None:
        mock_get = MagicMock()
    if mock_set is None:
        mock_set = MagicMock()
    return (
        patch("alphoryn.telemetry.otel._get_gcp_exporters", mock_get),
        patch("alphoryn.telemetry.otel._maybe_set_otel_providers", mock_set),
    )


@pytest.fixture(autouse=True)
def _clean_semconv_env(monkeypatch):
    monkeypatch.delenv("OTEL_SEMCONV_STABILITY_OPT_IN", raising=False)


# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------


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


def test_setup_otel_opts_into_experimental_genai_semconv(monkeypatch) -> None:
    """Without this opt-in the system prompt and tool definitions are not recorded."""
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    assert os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "gen_ai_latest_experimental"


# ---------------------------------------------------------------------------
# _enable_experimental_genai_semconv
# ---------------------------------------------------------------------------


def test_enable_experimental_semconv_sets_when_unset(monkeypatch) -> None:
    _enable_experimental_genai_semconv()
    assert os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "gen_ai_latest_experimental"


def test_enable_experimental_semconv_appends_to_other_opt_ins(monkeypatch) -> None:
    """The variable is a shared CSV, so other instrumentations' tokens survive."""
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    _enable_experimental_genai_semconv()
    assert os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "http,gen_ai_latest_experimental"


def test_enable_experimental_semconv_is_idempotent(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
    _enable_experimental_genai_semconv()
    assert os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "gen_ai_latest_experimental"


def test_enable_experimental_semconv_respects_explicit_stable(monkeypatch) -> None:
    """An operator who asked for stable keeps stable."""
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "stable")
    _enable_experimental_genai_semconv()
    assert os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "stable"


# ---------------------------------------------------------------------------
# Exporter wiring
# ---------------------------------------------------------------------------


def test_setup_otel_calls_get_gcp_exporters_with_tracing_and_logging(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    mock_get = MagicMock()
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2:
        setup_otel()
    mock_get.assert_called_once_with(enable_cloud_tracing=True, enable_cloud_logging=True)


def test_setup_otel_passes_exporters_to_maybe_set() -> None:
    mock_exporters = MagicMock()
    mock_get = MagicMock(return_value=mock_exporters)
    mock_set = MagicMock()
    p1, p2 = _patched_otel(mock_get=mock_get, mock_set=mock_set)
    with p1, p2:
        setup_otel()
    mock_set.assert_called_once_with([mock_exporters])


def test_setup_otel_sets_project_id_resource_attribute(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == "gcp.project_id=test-project"


def test_setup_otel_returns_the_resolved_project_id() -> None:
    """The CLI shows this: telemetry landing in the wrong project looks like none."""
    p1, p2 = _patched_otel()
    with p1, p2:
        assert setup_otel() == "test-project"


def test_setup_otel_registers_an_exit_flush(_no_real_atexit_registration) -> None:
    p1, p2 = _patched_otel()
    with p1, p2:
        setup_otel()
    _no_real_atexit_registration.assert_called_once_with(flush_otel)


# ---------------------------------------------------------------------------
# Failure is loud (gap 3): every path below used to warn and continue untraced
# ---------------------------------------------------------------------------


def test_setup_otel_raises_when_google_auth_default_fails() -> None:
    p1, p2 = _patched_otel()
    target = "alphoryn.telemetry.otel.google.auth.default"
    with p1, p2, patch(target, side_effect=RuntimeError("no credentials")):
        with pytest.raises(TelemetrySetupError, match="could not resolve Google credentials"):
            setup_otel()


def test_setup_otel_raises_when_credentials_carry_no_project_id() -> None:
    """ADK returns empty hooks here rather than raising, so we must catch it."""
    p1, p2 = _patched_otel()
    target = "alphoryn.telemetry.otel.google.auth.default"
    with p1, p2, patch(target, return_value=(MagicMock(), None)):
        with pytest.raises(TelemetrySetupError, match="no project ID"):
            setup_otel()


def test_setup_otel_raises_on_exporter_runtime_error() -> None:
    mock_get = MagicMock(side_effect=RuntimeError("gcp error"))
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2:
        with pytest.raises(TelemetrySetupError, match="could not build the GCP OTel exporters"):
            setup_otel()


def test_setup_otel_raises_on_missing_exporter_package() -> None:
    mock_get = MagicMock(side_effect=ImportError("opentelemetry-exporter-gcp-trace not installed"))
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2:
        with pytest.raises(TelemetrySetupError, match="could not build the GCP OTel exporters"):
            setup_otel()


def test_setup_otel_raises_when_no_tracer_provider_was_installed() -> None:
    """The silent path: no exception anywhere, and every span still dropped."""
    p1, p2 = _patched_otel()
    target = "alphoryn.telemetry.otel.trace.get_tracer_provider"
    with p1, p2, patch(target, return_value=MagicMock()):
        with pytest.raises(TelemetrySetupError, match="no OpenTelemetry TracerProvider"):
            setup_otel()


def test_setup_otel_does_not_register_a_flush_when_setup_fails(
    _no_real_atexit_registration,
) -> None:
    mock_get = MagicMock(side_effect=RuntimeError("gcp error"))
    p1, p2 = _patched_otel(mock_get=mock_get)
    with p1, p2, pytest.raises(TelemetrySetupError):
        setup_otel()
    _no_real_atexit_registration.assert_not_called()


# ---------------------------------------------------------------------------
# _verify_tracer_provider_installed
# ---------------------------------------------------------------------------


def test_verify_tracer_provider_accepts_a_real_sdk_provider() -> None:
    _verify_tracer_provider_installed()  # autouse fixture supplies a real one


def test_verify_tracer_provider_rejects_the_proxy_default() -> None:
    target = "alphoryn.telemetry.otel.trace.get_tracer_provider"
    with patch(target, return_value=MagicMock()):
        with pytest.raises(TelemetrySetupError):
            _verify_tracer_provider_installed()


# ---------------------------------------------------------------------------
# flush_otel
# ---------------------------------------------------------------------------


def test_flush_otel_force_flushes_the_installed_provider() -> None:
    provider = TracerProvider()
    target = "alphoryn.telemetry.otel.trace.get_tracer_provider"
    with patch(target, return_value=provider), patch.object(provider, "force_flush") as mock_flush:
        flush_otel()
    mock_flush.assert_called_once_with()


def test_flush_otel_is_a_noop_when_no_sdk_provider_is_installed() -> None:
    target = "alphoryn.telemetry.otel.trace.get_tracer_provider"
    with patch(target, return_value=MagicMock()):
        flush_otel()  # must not raise


def test_flush_otel_swallows_a_flush_failure(caplog) -> None:
    """Runs on the way out; must not mask whatever is already ending the run."""
    provider = TracerProvider()
    target = "alphoryn.telemetry.otel.trace.get_tracer_provider"
    with (
        patch(target, return_value=provider),
        patch.object(provider, "force_flush", side_effect=RuntimeError("export failed")),
        caplog.at_level("WARNING", logger="alphoryn.telemetry.otel"),
    ):
        flush_otel()
    assert any("OpenTelemetry flush failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _add_gcp_project_resource_attribute
# ---------------------------------------------------------------------------


def test_add_gcp_project_resource_attribute_sets_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    _add_gcp_project_resource_attribute("test-project")
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == "gcp.project_id=test-project"


def test_add_gcp_project_resource_attribute_merges_with_existing(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=custom")
    _add_gcp_project_resource_attribute("test-project")
    expected = "service.name=custom,gcp.project_id=test-project"
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == expected


def test_add_gcp_project_resource_attribute_noop_if_already_present(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "gcp.project_id=already-set")
    _add_gcp_project_resource_attribute("test-project")
    assert os.environ["OTEL_RESOURCE_ATTRIBUTES"] == "gcp.project_id=already-set"
