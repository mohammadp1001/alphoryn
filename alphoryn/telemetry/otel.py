"""OpenTelemetry setup using Google ADK's built-in GCP exporters.

Call setup_otel() once at CLI startup, before any agent is initialized.
Traces and spans then flow automatically to Cloud Trace and Cloud Logging.

To capture full prompt/response content in traces, set:
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
"""

import logging
import os

import google.auth
from google.adk.telemetry.google_cloud import get_gcp_exporters as _get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers as _maybe_set_otel_providers

_logger = logging.getLogger(__name__)

_SERVICE_NAME = "alphoryn"


def _add_gcp_project_resource_attribute(project_id: str) -> None:
    """Merge gcp.project_id into OTEL_RESOURCE_ATTRIBUTES if not already set.

    telemetry.googleapis.com rejects any span batch whose OTel Resource lacks
    this attribute (HTTP 400: 'Resource is missing required attribute
    "gcp.project_id"'). ADK's default resource detector only reads it from
    the standard OTEL_RESOURCE_ATTRIBUTES env var, so it must be present
    before maybe_set_otel_providers() builds the TracerProvider.
    """
    existing = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    if "gcp.project_id" in existing:
        return
    attr = f"gcp.project_id={project_id}"
    os.environ["OTEL_RESOURCE_ATTRIBUTES"] = f"{existing},{attr}" if existing else attr


def setup_otel() -> None:
    """Configure OTel providers with GCP exporters.

    Sets OTEL_SERVICE_NAME and wires up Cloud Trace + Cloud Logging exporters
    via the ADK helper. Fails silently — a logging failure never blocks startup.

    GenAI content capture is enabled by default so prompt/response reasoning
    is visible in Cloud Logging. Override with:
      OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false
    """
    os.environ.setdefault("OTEL_SERVICE_NAME", _SERVICE_NAME)
    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    try:
        _, project_id = google.auth.default()
        if project_id:
            _add_gcp_project_resource_attribute(project_id)
        gcp_exporters = _get_gcp_exporters(
            enable_cloud_tracing=True, enable_cloud_logging=True
        )
        _maybe_set_otel_providers([gcp_exporters])
    except Exception as exc:
        _logger.warning("OpenTelemetry setup failed, traces will not be exported: %s", exc)
