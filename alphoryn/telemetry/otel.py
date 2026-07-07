"""OpenTelemetry setup using Google ADK's built-in GCP exporters.

Call setup_otel() once at CLI startup, before any agent is initialized.
Traces and spans then flow automatically to Cloud Trace and Cloud Logging.

To capture full prompt/response content in traces, set:
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
"""

import logging
import os

from google.adk.telemetry.google_cloud import get_gcp_exporters as _get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers as _maybe_set_otel_providers

_logger = logging.getLogger(__name__)

_SERVICE_NAME = "alphoryn"


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
        gcp_exporters = _get_gcp_exporters(enable_cloud_logging=True)
        _maybe_set_otel_providers([gcp_exporters])
    except Exception as exc:
        _logger.warning("OpenTelemetry setup failed, traces will not be exported: %s", exc)
