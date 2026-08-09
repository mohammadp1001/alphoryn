"""OpenTelemetry setup using Google ADK's built-in GCP exporters.

Call setup_otel() once at CLI startup, before any agent is initialized.
Traces and spans then flow automatically to Cloud Trace and Cloud Logging.

Setup is a *preflight check*, not a logging call: it raises TelemetrySetupError
rather than warning and continuing. Constitution Principle IV ("a logging
failure never blocks execution") governs per-event emission at run time - see
TelemetryLogger.emit, which still falls back to stderr. Discovering at startup
that nothing will be recorded at all is the same class of problem as an invalid
config, and the CLI treats it the same way: report it and exit 1, rather than
trade blind for hours and leave no record of why.

Full LLM capture (system prompt, tool definitions, input/output messages) needs
the experimental GenAI semantic conventions, which setup_otel() opts into by
default. Override either of these to change what is captured:
  OTEL_SEMCONV_STABILITY_OPT_IN=stable
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false
"""

import atexit
import logging
import os

import google.auth
from google.adk.telemetry.google_cloud import get_gcp_exporters as _get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers as _maybe_set_otel_providers
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

_logger = logging.getLogger(__name__)

_SERVICE_NAME = "alphoryn"

# Opt-in token for the experimental GenAI semantic conventions. Only this path
# records gen_ai.system_instructions and gen_ai.tool_definitions; the stable
# path emits user/system/choice log events but never the tool definitions the
# model was given, so a trace cannot tell you what the agent could have done.
_GENAI_EXPERIMENTAL_OPT_IN = "gen_ai_latest_experimental"


class TelemetrySetupError(RuntimeError):
    """Raised when OpenTelemetry cannot be wired up to export anything."""


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


def _enable_experimental_genai_semconv() -> None:
    """Add the experimental GenAI opt-in to OTEL_SEMCONV_STABILITY_OPT_IN.

    The variable is a CSV of opt-in tokens shared with other instrumentations,
    so an existing value is appended to rather than replaced.
    """
    existing = os.environ.get("OTEL_SEMCONV_STABILITY_OPT_IN", "")
    tokens = [t.strip() for t in existing.split(",") if t.strip()]
    if _GENAI_EXPERIMENTAL_OPT_IN in tokens or "stable" in tokens:
        return
    tokens.append(_GENAI_EXPERIMENTAL_OPT_IN)
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = ",".join(tokens)


def _verify_tracer_provider_installed() -> None:
    """Fail if no real SDK TracerProvider ended up installed.

    get_gcp_exporters() returns an empty OTelHooks (no exception) when it
    cannot determine the GCP project, and maybe_set_otel_providers() only
    installs a TracerProvider when at least one span processor exists. Without
    this check that path completes silently and every span is dropped for the
    whole process. The global default is a ProxyTracerProvider, so an isinstance
    check against the SDK type is what distinguishes "wired up" from "no-op".
    """
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        raise TelemetrySetupError(
            "no OpenTelemetry TracerProvider was installed, so no spans would be "
            "exported. This usually means the GCP project could not be resolved "
            "from your credentials - check `gcloud auth application-default login` "
            "and GOOGLE_CLOUD_PROJECT."
        )


def flush_otel() -> None:
    """Force-export any spans still buffered in the BatchSpanProcessor.

    Spans are batched in memory and shipped every few seconds. The SDK flushes
    on a clean interpreter exit, but a crash or a hard kill loses whatever is
    still buffered - which is exactly the tail of the run you most want to read
    afterwards. Never raises: this runs on the way out, and a flush failure must
    not mask the error that is already ending the run.
    """
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        return
    try:
        provider.force_flush()
    except Exception as exc:
        _logger.warning("OpenTelemetry flush failed, buffered spans may be lost: %s", exc)


def setup_otel() -> str:
    """Configure OTel providers with GCP exporters and return the GCP project ID.

    Sets OTEL_SERVICE_NAME, opts into the experimental GenAI semantic
    conventions and full content capture, then wires up the Cloud Trace +
    Cloud Logging exporters via the ADK helper and registers an exit flush.

    Returns:
        The GCP project ID traces will be written to. The caller is expected to
        show this to the user - sending a run's telemetry to the wrong project
        looks identical to sending none at all.

    Raises:
        TelemetrySetupError: if nothing would be exported. Callers should treat
            this like a config error and exit rather than run untraced.
    """
    os.environ.setdefault("OTEL_SERVICE_NAME", _SERVICE_NAME)
    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    _enable_experimental_genai_semconv()

    try:
        _, project_id = google.auth.default()
    except Exception as exc:
        raise TelemetrySetupError(
            f"could not resolve Google credentials: {exc}. "
            "Run `gcloud auth application-default login`."
        ) from exc

    if not project_id:
        raise TelemetrySetupError(
            "Google credentials resolved but carry no project ID. "
            "Set GOOGLE_CLOUD_PROJECT (this project expects `alphoryn`)."
        )

    _add_gcp_project_resource_attribute(project_id)

    try:
        gcp_exporters = _get_gcp_exporters(enable_cloud_tracing=True, enable_cloud_logging=True)
        _maybe_set_otel_providers([gcp_exporters])
    except Exception as exc:
        raise TelemetrySetupError(f"could not build the GCP OTel exporters: {exc}") from exc

    _verify_tracer_provider_installed()
    atexit.register(flush_otel)
    return project_id
