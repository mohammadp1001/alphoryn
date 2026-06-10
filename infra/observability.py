"""
Observability: Cloud Trace (OpenTelemetry) + Cloud Logging.
ADK emits invocation/agent_run/call_llm/execute_tool spans automatically.
This module adds our custom span layer (decision cycles, API calls, HITL, SQLite writes)
and configures structured logging with trace ID injection.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_tracer: trace.Tracer | None = None
_session_trace_id: str | None = None


def setup_observability(session_id: str) -> None:
    """
    Initialise OTel + Cloud Logging for this session.
    Call once at session start before any agent work.
    """
    global _tracer, _session_trace_id
    _session_trace_id = session_id

    resource = Resource.create({"service.name": "algotrade-agent", "session.id": session_id})

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id:
        _setup_cloud_trace(resource, project_id, session_id)
        _setup_cloud_logging(project_id, session_id)
    else:
        # Local dev: console exporter only
        _setup_local_trace(resource)
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

    _tracer = trace.get_tracer("algotrade.agent")


def _setup_cloud_trace(resource: Resource, project_id: str, session_id: str) -> None:
    try:
        from opentelemetry.exporter.cloud_trace import (
            CloudTraceSpanExporter,  # type: ignore[import]
        )

        provider = TracerProvider(resource=resource)
        exporter = CloudTraceSpanExporter(project_id=project_id)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    except ImportError:
        logging.warning("opentelemetry-exporter-gcp-trace not installed — falling back to local")
        _setup_local_trace(resource)


def _setup_local_trace(resource: Resource) -> None:
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def _setup_cloud_logging(project_id: str, session_id: str) -> None:
    try:
        import google.cloud.logging  # type: ignore[import]

        client = google.cloud.logging.Client(project=project_id)
        client.setup_logging(log_level=logging.INFO)
    except ImportError:
        logging.basicConfig(level=logging.INFO)

    # Inject session/trace IDs into every log record
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        record.session_id = session_id  # type: ignore[attr-defined]
        return record

    logging.setLogRecordFactory(record_factory)


# ── Custom span helpers ───────────────────────────────────────────────────────

@contextmanager
def span(name: str, **attributes: Any) -> Generator[trace.Span, None, None]:
    """Context manager for a custom child span with optional attributes."""
    tracer = _tracer or trace.get_tracer("algotrade.agent")
    with tracer.start_as_current_span(name) as s:
        for k, v in attributes.items():
            s.set_attribute(k, str(v))
        yield s


@contextmanager
def decision_cycle_span(cycle_index: int, strategy: str, regime: str) -> Generator[trace.Span, None, None]:
    """Parent span for one full decision cycle."""
    with span(
        "decision_cycle",
        cycle_index=cycle_index,
        strategy=strategy,
        market_regime=regime,
    ) as s:
        yield s


@contextmanager
def subagent_span(agent_name: str, **kwargs: Any) -> Generator[trace.Span, None, None]:
    with span(f"subagent.{agent_name}", agent=agent_name, **kwargs) as s:
        yield s


@contextmanager
def api_call_span(api: str, operation: str, **kwargs: Any) -> Generator[trace.Span, None, None]:
    with span(f"api.{api}.{operation}", api=api, operation=operation, **kwargs) as s:
        yield s


@contextmanager
def hitl_span(proposed_action: str) -> Generator[trace.Span, None, None]:
    with span("hitl.prompt", proposed_action=proposed_action) as s:
        yield s


@contextmanager
def db_write_span(table: str, record_id: str) -> Generator[trace.Span, None, None]:
    with span("db.write", table=table, record_id=record_id) as s:
        yield s


# ── Structured logger ─────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
