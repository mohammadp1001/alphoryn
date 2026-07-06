<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.3 → 1.1.0
Modified principles:
  - Principle III: Session budget generalized from 1H-specific minutes to
    timeframe-relative fractions (80% investigate / 20% decide+execute).
Added sections: None
Removed sections: None
Changed sections:
  - Development Standards: Added 10min and 15min candle timeframes (testing only);
    added extended_hours config flag for integration test use.
Templates requiring updates:
  ✅ .specify/templates/plan-template.md — no change needed
  ✅ .specify/templates/spec-template.md — no change needed
  ✅ .specify/templates/tasks-template.md — no change needed
Follow-up TODOs:
  - alphoryn/config/models.py: Add "10min" and "15min" to _TIMEFRAME_SECONDS and
    AlphorynConfig.candle_timeframe Literal; add extended_hours: bool = False field.
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
as a fraction of the candle timeframe: **≤ 80% for investigation** and **≤ 20% for
decide + execute**. For a 1H candle this is 48 min / 12 min; for a 15min candle it is
12 min / 3 min; for a 10min candle it is 8 min / 2 min. An overrun MUST force
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
- Investigation MUST complete within 80% of the candle timeframe; any sub-step
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
  exchange, ETFs, extended hours) MUST be sourced from a single config file; no hardcoded
  values in logic
- **Candle timeframes**: Valid values are `10min`, `15min`, `30min`, `1H`, and `4H`.
  `10min` and `15min` are intended for integration testing and development only —
  production runs SHOULD use `30min` or longer. Extended hours (`extended_hours: true`)
  is likewise a testing affordance that allows the scheduler to execute outside regular
  market hours using Alpaca's extended-hours paper API; it MUST NOT be enabled for
  production configurations.
- **Logging**: Structured (JSON-serialisable) log entries at every failure boundary and
  session lifecycle event; human-readable console output is secondary

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

**Version**: 1.1.0 | **Ratified**: 2026-07-03 | **Last Amended**: 2026-07-06
