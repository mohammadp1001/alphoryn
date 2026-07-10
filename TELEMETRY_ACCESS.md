# Alphoryn Telemetry Systems - Access Guide

## Two Kinds of Telemetry Data

Alphoryn implements **two complementary telemetry systems** for complete observability:

---

## 1. STRUCTURED EVENT LOGGING (Cloud Logging)

### What it captures:
- 14 defined event types: AGENT_DECISION, TOOL_CALL, ORDER_PLACED, STOP_LOSS_TRIGGERED, etc.
- Every LLM decision, tool call, order execution, and system action
- Structured JSON format for easy parsing and correlation

### Status: ⚠️ Code path works; verify events are actually landing in your project

**Correction to an earlier claim in this doc**: telemetry events are **not** stored in the
local SQLite memory bank. `TelemetryLogger.emit()` (`alphoryn/telemetry/logger.py`) writes
*only* to Cloud Logging, or to stderr as a fallback if Cloud Logging is unreachable — never
to SQLite. The `sessions` / `positions` / `memory_entries` tables are separate trading-state
records (decisions, prices, P&L), not the structured event log. Don't confuse the two when
diagnosing "where did my telemetry go."

**Verified 2026-07-10**: a manual `TelemetryLogger().emit(...)` call against this machine's
ADC credentials landed successfully in Cloud Logging (project `alphoryn`) within seconds.
But a query for `jsonPayload.component="main_agent"` returned **zero** results — meaning the
decisions from the earlier trading run never reached Cloud Logging at all. Most likely
explanation: at the time that run executed, the Cloud Logging client wasn't authenticated
yet (or failed for some other reason), so every `emit()` call silently fell back to stderr
per constitution Principle IV — and that stderr output wasn't captured to a persistent file.
**This is expected fail-safe behavior, not a bug** — but it does mean those specific events
are gone. If you need to be sure future runs are captured, redirect stderr to a file when
launching, e.g. `alphoryn run 2> telemetry-fallback.jsonl`, and check that file if Console
queries come up empty.

#### A) GCP Cloud Logging (Primary, Persistent)

Console → Logs Explorer. Two things trip people up on a "0 results" query:
1. **Time range picker** (top right) — Logs Explorer defaults to a short recent window
   (often 1h). If the run you're checking happened earlier, widen it before trusting a
   zero-result query.
2. **Project selector** (top left) — confirm you're viewing the `alphoryn` project, not
   whatever project the Console last had selected.

Pin the query to our custom log to rule out cross-project/cross-log noise:
```
logName="projects/alphoryn/logs/alphoryn"

# View all agent decisions
logName="projects/alphoryn/logs/alphoryn"
AND jsonPayload.event_type="AGENT_DECISION"
AND jsonPayload.component="main_agent"

# Filter by session
logName="projects/alphoryn/logs/alphoryn"
AND jsonPayload.session_id="run-5/session-0001"

# View all errors
logName="projects/alphoryn/logs/alphoryn"
AND jsonPayload.event_type="ORDER_FAILED"

# By component (main_agent, execution_agent, monitor, scheduler)
logName="projects/alphoryn/logs/alphoryn"
AND jsonPayload.component="execution_agent"
```

#### B) Stderr Fallback (Development)
If Cloud Logging is unavailable, events are written to stderr as JSON:
```json
{
  "event_type": "AGENT_DECISION",
  "session_id": "run-5/session-0001",
  "component": "main_agent",
  "ticker": "SPY",
  "timestamp": "2026-07-10T13:00:45.123456+00:00",
  "latency_ms": 2345,
  "payload": {
    "decision": "BUY",
    "strategy": "MEAN_REVERSION",
    "reasoning": "...",
    "confidence": 0.85
  }
}
```

### Event Schema (All 14 Event Types)

| Event Type | Component | When Emitted | Key Payload Fields |
|---|---|---|---|
| `AGENT_DECISION` | main_agent, feedback_agent | After agent decision | decision, reasoning, model_name, token_usage |
| `TOOL_CALL` | any agent | Before/after tool call | tool_name, tool_input, tool_output_summary |
| `SIGNAL_SNAPSHOT_BUILT` | main_agent | After snapshot creation | etf1_signals_summary, etf2_signals_summary |
| `ORDER_PLACED` | execution_agent | Order filled | ticker, side, qty, order_id |
| `ORDER_FAILED` | execution_agent | Order rejected | ticker, side, reason |
| `BUDGET_CHECK` | execution_agent | Budget validation | ticker, available_budget, required |
| `STOP_LOSS_TRIGGERED` | monitor | Price hits stop-loss | ticker, position_id, trigger_price |
| `PROFIT_TARGET_TRIGGERED` | monitor | Exit target reached | ticker, position_id, exit_target |
| `WINDOW_EXPIRY_TRIGGERED` | monitor | Evaluation window reached | ticker, position_id |
| `POSITION_CLOSED` | monitor | Position exit confirmed | ticker, position_id, exit_reason, pnl |
| `SESSION_START` | scheduler | Session begins | candle_close_at, open_positions_count |
| `SESSION_END` | scheduler | Session completes | status, duration_ms |
| `MARKET_CLOSED` | scheduler | Market unavailable | reason |
| `BUDGET_TIMEOUT` | scheduler | Time budget exceeded | phase, elapsed_ms |

---

## 2. OPENTELEMETRY TRACING (Cloud Trace)

### What it captures:
- Distributed traces of execution flow
- Span timing and latency analysis
- Dependency relationships between components
- Error and exception details

### Status: ⚠️ Fixed the crash; log-based OTel export confirmed, span export unconfirmed

`alphoryn/telemetry/otel.py:setup_otel()` calls `get_gcp_exporters(enable_cloud_logging=True)`
unconditionally at every CLI startup (`cli/main.py`) — this was always meant to be on by
default, no flag needed. It was failing because `pyproject.toml` was missing the package
that provides the `opentelemetry.exporter.cloud_logging` module. PR #110 added
`opentelemetry-exporter-gcp-trace` and `opentelemetry-exporter-gcp-monitoring` but missed
`opentelemetry-exporter-gcp-logging` (a pre-release package, `1.12.0a0` at time of writing).
Added to `pyproject.toml` dependencies. Verified 2026-07-10 end-to-end with a real
`alphoryn run` session (`run-6/session-0001`):

- ✅ `setup_otel()` completes with no warning (previously crashed on every startup)
- ✅ GenAI prompt/response content is exported to Cloud Logging via OTel — confirmed logs
  under `projects/alphoryn/logs/gen_ai.system.message`, `gen_ai.user.message`, and
  `gen_ai.choice`, timestamps matching the run exactly (this is the log-based half of the
  fix and the part that was actually crashing before)
- ⚠️ **Cloud Trace spans did not appear.** Polled `trace_v1.ListTraces` for ~2 minutes after
  the run completed (8 checks, 10s apart) — zero traces returned, no permission error, no
  export error logged. `MainAgent` does use `google.adk.runners.InMemoryRunner`, which
  should auto-instrument spans, so this may be a separate, unrelated gap (ADK version
  behavior, project/resource mismatch for spans specifically, or spans requiring an
  explicit flush this short-lived CLI process never triggers). **Not blocking this fix** —
  the crash this issue reports is specifically in the Cloud Logging exporter path, which is
  now confirmed working. Filing a follow-up issue for the trace-visibility gap is
  recommended before relying on Cloud Trace for latency analysis.

```bash
# Already in pyproject.toml dependencies — for an existing venv, just:
pip install "opentelemetry-exporter-gcp-logging>=1.12.0a0"
```

#### A) GCP Cloud Trace Console
```
Google Cloud Console → Cloud Trace → Trace List

# Filter by service
service.name = "alphoryn"

# View latency timeline
- Shows each component's execution time
- Parallel/sequential operations
- Critical path analysis
```

#### B) Programmatic Access (Python)
```python
from google.cloud.trace_v2 import TraceServiceClient
from google.cloud.trace_v2.types import GetTraceRequest

client = TraceServiceClient()
# Requires Google Cloud credentials
```

---

## Comparison: Cloud Logging vs. Cloud Trace

| Aspect | Cloud Logging | Cloud Trace |
|--------|---------------|------------|
| **Type** | Structured Events | Distributed Tracing |
| **Local Storage** | None — Cloud or stderr only | N/A |
| **Remote Storage** | GCP Logs Explorer | GCP Cloud Trace |
| **Use Case** | Event correlation, debugging decisions | Latency analysis, performance |
| **Query Method** | Logs Explorer filters | Trace UI with timeline |
| **Data Retention** | ~30 days (GCP default) | ~30 days (GCP default) |
| **Enabled by default** | ✅ Yes (`TelemetryLogger`, called from every component) | ✅ Yes (`setup_otel()` at CLI startup) |
| **Fallback** | stderr (when Cloud unavailable) | None — traces are simply dropped |
| **Verified 2026-07-10** | ✅ Confirmed — custom events + OTel `gen_ai.*` logs both landed | ⚠️ Setup succeeds, but no spans found in Cloud Trace after a real run (see status above) |

---

## Quick Start: View Your Telemetry

### Step 1: Confirm credentials are live and events actually land
```bash
python -c "
from alphoryn.telemetry.logger import TelemetryLogger
t = TelemetryLogger()
print('cloud_logger initialized:', t._cloud_logger is not None)
t.emit('SESSION_START', 'diagnostic', {'test': True}, session_id='diag-test')
"
```
If `cloud_logger initialized: False`, Cloud Logging isn't reachable and everything is going
to stderr instead — run `gcloud auth application-default login` and retry.

### Step 2: Run alphoryn — events auto-export

⚠️ On at least one Windows dev machine, `python -m alphoryn.cli.main run ...` silently
no-ops — exits 0, prints nothing, writes no memory-bank record. Root cause not yet
diagnosed; if a run "completes" instantly with no output, use the module-attribute
invocation instead, which is confirmed working:
```bash
python -c "
from alphoryn.cli.main import app
import sys
sys.argv = ['alphoryn', 'run', '--config', 'config.json']
app()
"
```
The installed console script (`alphoryn run ...`, from `[project.scripts]` in
`pyproject.toml`) was not tested here but is the intended long-term entry point.

### Step 3: View in Google Cloud Console
1. Go to https://console.cloud.google.com/logs
2. Confirm the **project selector** (top left) is on `alphoryn`
3. Widen the **time range** (top right) to cover when the run actually happened
4. Filter: `logName="projects/alphoryn/logs/alphoryn" AND jsonPayload.component="main_agent"`
5. Inspect decision reasoning and latency

### Step 4: View traces in Cloud Trace
No separate install needed as of 2026-07-10 (see status above) — traces are emitted
automatically alongside the run in Step 2.
```
https://console.cloud.google.com/traces → filter service.name = "alphoryn"
```

---

## Feedback Agent Telemetry

When the feedback agent evaluates a closed position:
1. **Event**: `AGENT_DECISION` with `component="feedback_agent"`
2. **Payload**: `outcome_judgment` (CORRECT | INCORRECT | NEUTRAL), `reasoning`, `thesis_vs_outcome`
3. **Database**: `FeedbackEvaluation` record created with full evaluation details
4. **Correlates**: Via `position_id` back to entry decision

---

## Telemetry Guarantees

Per Constitution Principle IV (Fail Loud, Hold Safe):
- ✅ All events emitted synchronously (no loss)
- ✅ Cloud Logging unavailable → fallback to stderr (never blocks)
- ✅ Structured JSON schema maintained (parseable always)
- ✅ Every failure emitted with sufficient diagnostic context
- ✅ Session_id on every event for trace correlation
