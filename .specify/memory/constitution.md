<!--
SYNC IMPACT REPORT
==================
Version change: 1.1.0 → 1.2.0
Modified principles:
  - Principle III: Session budget percentages corrected from 80/20 to ~87/13
    to match actual implementation (52 min investigate / 7 min decide+execute
    for a 1H candle). Example values for 10min and 4H candles added.
Added sections: None
Removed sections: None
Changed sections:
  - Development Standards: "ETFs" → "tickers" (PR #99 terminology refactor).
  - Development Standards: Removed "15min" candle timeframe (not implemented in V0.0.1).
  - Development Standards: Added Secret Management standard (Google Secret Manager,
    ADC for GCP auth — never store API credentials in config files or repo).
  - Development Standards: Expanded Logging standard to document both telemetry
    streams (Cloud Logging structured events + OTel/Cloud Trace via ADK exporters).
Templates requiring updates:
  ✅ .specify/templates/plan-template.md — no change needed (generic)
  ✅ .specify/templates/spec-template.md — no change needed (generic)
  ✅ .specify/templates/tasks-template.md — no change needed (generic)
Follow-up TODOs:
  - alphoryn/scheduler/scheduler.py: Session budget is hardcoded at 52 min / 7 min.
    Consider making it proportional to candle_timeframe (87% / 12%) so shorter
    candles used in testing also get proportional budgets automatically.
  - alphoryn/telemetry/otel.py: opentelemetry-exporter-gcp-* package is missing;
    OTel traces are not reaching Cloud Trace. File a GitHub issue to add the
    dependency and verify the export pipeline.
-->

# Alphoryn Constitution

## Core Principles

### I. Determinism in Execution

The execution agent and all deterministic workflow components (stop-loss, profit target,
window expiry) MUST produce identical outputs given identical inputs. No randomness,
no implicit state, no side effects outside structured logging. If a deterministic component
cannot execute cleanly, it MUST halt and log — never proceed with partial state.

**Rationale**: Execution is the irreversible layer. A bug in investigation is recoverable;
a bug in execution may leave positions in an unknown state.

### II. Test Coverage is Non-Negotiable

All Python code MUST maintain 100% test coverage enforced by CI. `pragma: no cover` is
forbidden. Ruff MUST pass with zero violations on every PR. LLM-assisted agent paths MUST
have integration tests using recorded or stubbed API responses — not mocks that paper over
real behavior.

**Rationale**: Matches the project CI gates already established; paper trading errors
discovered by tests are free, errors discovered at runtime are not.

### III. Session Budget is Enforced, Not Advisory

Every session step MUST complete within its defined time budget. The budget is expressed
as a fraction of the candle timeframe: **≤ 87% for investigation** and **≤ 13% for
decide + execute**. For a 1H candle this is 52 min / 7 min; for a 4H candle it is
208 min / 28 min; for a 10min candle it is 8 min / 1 min. An overrun MUST force
a **Hold** decision and emit a structured warning log. The system MUST never silently skip
a budget check or proceed past a timeout hoping to finish in time.

**Rationale**: The candle timeframe is a hard wall. Decisions that bleed into the next
candle corrupt the data assumptions the strategy was built on. Shorter candles used in
integration testing have the same proportional constraint.

### IV. Fail Loud, Hold Safe

Any failure condition (API unavailable, market closed, budget exceeded, MCP skill
unavailable) MUST result in a **Hold** action plus a structured log entry with enough
context to diagnose the failure. Silent failures are forbidden. The system MUST never
leave a position in an ambiguous open/closed state. If the telemetry logging backend
(Cloud Logging) is itself unavailable, the failure MUST be written to stderr and execution
MUST continue — a logging failure is never grounds for a Hold or abort.

**Rationale**: Paper trading tolerates incorrect decisions; it cannot tolerate unknown
system state. Every failure must be observable and recoverable.

### V. Snapshot Isolation for Investigation

The main agent MUST reason exclusively over the frozen `SignalSnapshot` returned by the
`build_snapshot` tool. No live data MUST be fetched after `build_snapshot` returns and
before the session decision is finalised. This restriction applies to the investigation
phase only — the feedback agent MAY fetch live data (candle close price) during the
evaluation phase, which runs outside investigation. The snapshot timestamp MUST be
recorded in the session HTML report.

**Rationale**: Prevents mid-investigation data drift and ensures decisions are
reproducible when reviewed via the feedback agent or HTML reports.

## Performance Requirements

- Candle-close-to-first-action latency MUST be under 60 seconds (data fetch + snapshot).
- Investigation MUST complete within 87% of the candle timeframe; any sub-step
  exceeding its share triggers a Hold, not a retry.
- The stop-loss monitoring loop MUST poll at an interval short enough to react within
  one candle period (poll interval ≤ min(30 seconds, candle_seconds / 4)).
- Paper trading API calls MUST be retried at most once on transient failure; persistent
  failure falls through to the Fail Loud principle above.

## Development Standards

- **Language**: Python 3.13+
- **Linting/Formatting**: Ruff (zero violations required)
- **Testing**: pytest, 100% coverage, no `pragma: no cover`
- **Agent SDK**: Google ADK — use Gemini models for main and feedback agents
- **Config**: All user-tunable parameters (candle timeframe, run duration, money budget,
  tickers, extended hours) MUST be sourced from a single config file; no hardcoded
  values in logic
- **Secret Management**: API credentials (Alpaca API key and secret) MUST be stored in
  Google Secret Manager and retrieved at runtime via Application Default Credentials (ADC).
  Credentials MUST NOT appear in config files, environment files, or the git repository.
  GCP project: `alphoryn`. Secret names: `alpaca-api-key`, `alpaca-api-secret`.
- **Candle timeframes**: Valid values are `10min`, `30min`, `1H`, and `4H`.
  `10min` is intended for integration testing and development only —
  production runs SHOULD use `30min` or longer. Extended hours (`extended_hours: true`)
  is likewise a testing affordance that allows the scheduler to execute outside regular
  market hours using Alpaca's extended-hours paper API; it MUST NOT be enabled for
  production configurations.
- **Logging**: Two independent telemetry streams MUST be active at runtime:
  (1) Structured JSON events via `TelemetryLogger` → GCP Cloud Logging (log name
  `alphoryn`); covers all 14 event types at every failure boundary and session lifecycle
  event. Fallback to stderr if Cloud Logging is unavailable — never block execution.
  (2) OTel traces via Google ADK's GCP exporters → Cloud Trace; covers LLM agent
  invocations (spans, token counts, latency). OTel setup failure MUST be non-fatal.
  Human-readable console output is secondary to both structured streams.

## Governance

This constitution supersedes all other practices documented in this project. When a PR
or design decision conflicts with a principle, the principle wins unless an amendment
is ratified first.

**Amendment procedure**: Edit this file, increment the version (MAJOR for principle
removal/redefinition; MINOR for new principle or section; PATCH for clarifications),
update `Last Amended`, and commit with message
`docs: amend constitution to vX.Y.Z (<reason>)`.

All PRs MUST pass the CI gates defined in Principle II before merge. The Constitution
Check section in `plan-template.md` MUST be completed before Phase 0 research begins
on any feature.

**Version**: 1.2.0 | **Ratified**: 2026-07-03 | **Last Amended**: 2026-07-07
