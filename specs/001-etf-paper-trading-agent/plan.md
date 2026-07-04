# Implementation Plan: Alphoryn — Automated ETF Paper Trading System

**Branch**: `001-etf-paper-trading-agent` | **Date**: 2026-07-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-etf-paper-trading-agent/spec.md`

## Summary

Alphoryn V0.0.1 is a CLI application for automated ETF paper trading driven by LLM agents
(Google ADK + Gemini). The user configures a session via a JSON config file with optional
CLI argument overrides. The system autonomously executes a candle-by-candle
investigate-decide-execute loop for two user-supplied ETFs. A local SQLite database serves
as the memory bank; API credentials are managed via Google Secret Manager. Paper trading
and market data are provided by Alpaca (via `alpaca-py` SDK for deterministic components
and the Alpaca MCP server as tools for LLM agents). Every LLM agent decision emits a
structured event log (decisions, tool calls, orders, monitor triggers) to Cloud Logging.

---

## Technical Context

**Language/Version**: Python 3.13+

**Primary Dependencies**:
- `google-adk` — Google ADK agent framework (main agent, feedback agent; Gemini models)
- `alpaca-py` — Alpaca SDK for deterministic components (market data snapshots, order execution, position monitoring, stop-loss polling)
- `alpaca-mcp-server` — Alpaca MCP server configured as tool provider for LLM agents (order management, market data, account info, market calendar)
- `typer` — CLI framework (argument parsing + JSON config file override)
- `pydantic` + `pydantic-settings` — config validation and layered loading
- `sqlalchemy` — SQLite ORM for memory bank (schema, queries, migrations)
- `google-cloud-secret-manager` — API key retrieval at runtime
- `jinja2` — HTML report generation from per-strategy templates
- `google-cloud-logging` — structured event log upload (all component activity → GCP Cloud Logging)
- `ruff` — linting (zero violations; CI gate)
- `pytest` + `pytest-cov` — testing (100% coverage; CI gate)

**Storage**: SQLite via SQLAlchemy (local file, memory bank + session/position state);
local filesystem (HTML reports, JSON config, Jinja2 templates)

**Market scope**: Alpaca covers US equities (NYSE, NASDAQ, AMEX). ETFs must be US-listed.
Market hours are sourced from Alpaca's market calendar API; no exchange config needed.

**Testing**: pytest, 100% coverage enforced by CI. No `pragma: no cover`. Agent paths
(main agent, feedback agent) tested with recorded/stubbed Google ADK responses.

**Target Platform**: Single-process, single-machine CLI. Linux/macOS/Windows, Python 3.13+.

**Project Type**: CLI application

**Performance Goals**:
- Candle-close to first investigation action: ≤60 seconds (data fetch + snapshot build)
- Investigation heartbeat: every 5 minutes (user-visible aliveness signal)
- Stop-loss monitor poll interval: ≤30 seconds (react within one 1-minute candle)
- Session startup (config load + memory bank read + position load): ≤2 minutes

**Constraints**:
- Investigation agent calls `build_snapshot` ADK tool during pre-investigation; once it returns a frozen `SignalSnapshot`, no further market data tool calls occur during investigation (Principle V). `data_fetch` is internal to `market_data/client.py` — not exposed to the agent
- Execution agent (ADK BaseAgent, no LLM) and position monitor MUST be fully deterministic; determinism verified by zero model calls, not zero ADK calls
- Memory bank MUST be readable at startup — inaccessible/corrupt → hard abort with error
- 52-min investigation + 7-min execute time budgets enforced per session; overrun → Hold

**Scale/Scope**: Single user, two ETFs, one session active at a time, local execution.
Background stop-loss monitor runs as a separate thread alongside the session loop.

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Verification |
|---|---|---|
| I. Determinism in Execution | ✅ PASS | `execution/agent.py` is an ADK `BaseAgent` with no LLM model configured; `monitor/monitor.py` is pure Python. Both call only `alpaca-py` with fixed inputs. Unit tests mock Alpaca SDK responses and assert identical outputs for identical inputs. |
| II. Test Coverage | ✅ PASS | 100% pytest coverage enforced in CI. ADK agent paths tested with stubbed `google-adk` responses (see `research.md §Testing ADK Agents`). Ruff configured in `pyproject.toml`. |
| III. Session Budget Enforced | ✅ PASS | `scheduler/scheduler.py` enforces 52-min/7-min budgets via `asyncio.wait_for` with explicit Hold fallback. Heartbeat emitted every 5 min during investigation. |
| IV. Fail Loud, Hold Safe | ✅ PASS | All failure modes in spec FR-017 and design doc §Failure Handling table produce Hold + structured JSON log entry. No silent failures. |
| V. Snapshot Isolation | ✅ PASS | Main agent calls `build_snapshot` ADK tool during pre-investigation; `data_fetch` is internal and not agent-accessible. Once `build_snapshot` returns a frozen `SignalSnapshot`, the system prompt and integration tests prohibit any further market data tool calls during investigation (see `research.md §Snapshot Isolation`). |

No violations — Complexity Tracking not required.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-etf-paper-trading-agent/
├── plan.md              # This file
├── research.md          # Phase 0 decisions and rationale
├── data-model.md        # Phase 1 entity schema
├── quickstart.md        # Phase 1 setup guide
├── contracts/
│   ├── cli.md           # CLI command contract
│   └── config-schema.md # JSON config file schema
└── tasks.md             # Phase 2 output (/speckit-tasks — not yet created)
```

### Source Code (repository root)

```text
alphoryn/
├── cli/
│   └── main.py          # Typer app; entry point; config file + CLI override resolution
├── config/
│   ├── models.py        # Pydantic AlphorynConfig model (all session parameters)
│   └── loader.py        # Layered load: JSON file → CLI arg overrides → validated model
├── agents/
│   ├── main_agent.py    # Google ADK main agent (regime recognition + per-ETF decision)
│   ├── feedback_agent.py # Google ADK feedback agent (thesis vs outcome evaluation)
│   └── prompts.py       # Prompt templates for both agents
├── execution/
│   └── agent.py         # ADK BaseAgent (no LLM); deterministic Buy/Sell/Hold via Alpaca alpaca-py tools
├── monitor/
│   └── monitor.py       # Deterministic position monitor (stop-loss, profit target, window expiry)
├── scheduler/
│   └── scheduler.py     # Candle boundary alignment; market hours check; session budget enforcement
├── market_data/
│   └── client.py        # alpaca-py wrapper; internal data_fetch + signal computation; exposes build_snapshot as the sole ADK tool; price polling for stop-loss monitor
├── memory/
│   ├── schema.py        # SQLAlchemy models: Run, Session, Position, FeedbackEvaluation, MemoryEntry
│   └── bank.py          # Memory bank interface: read/write, startup load, corruption detection
├── reports/
│   └── generator.py     # Jinja2 HTML report builder (per-strategy templates)
├── secrets/
│   └── client.py        # Google Secret Manager wrapper (Alpaca API key + secret key; injects as env vars for MCP server)
├── telemetry/
│   ├── logger.py        # System-wide structured event emitter: sends JSON events to Cloud Logging for all components (agents, execution, monitor, scheduler)
├── strategies/          # Strategy signal rules (mean_reversion.md, momentum.md)
│   ├── mean_reversion.md
│   └── momentum.md
└── skills/              # Investigation skill files (identify_regime, entry, sizing, memory)

tests/
├── unit/                # Pure function tests; deterministic components
├── integration/         # Full session cycle with stubbed ADK + stubbed Alpaca
└── contract/            # CLI contract tests; config schema validation

templates/
└── reports/             # Jinja2 HTML templates (mean_reversion.html.j2, momentum.html.j2)

config.json              # Example configuration (non-secret values only)
pyproject.toml           # Dependencies, Ruff config, pytest config
```

**Structure Decision**: Single-project layout. Each top-level sub-package maps directly to
one agent or deterministic component from design doc §Agents table. `agents/` holds both
LLM-assisted agents; `execution/` holds the ADK BaseAgent execution agent (no LLM);
`monitor/` holds the pure-Python deterministic position monitor; `memory/` holds the SQLite
bank; `market_data/` and `secrets/` hold external integrations; `telemetry/` holds the
structured event logging layer used by all components (agents, execution, monitor, scheduler).
This makes constitution Principle I (Determinism) trivially verifiable: any file under
`execution/` or `monitor/` must contain zero LLM model calls.

---

## Implementation Cross-References

For each source package, the authoritative design doc section(s) to consult during
implementation. All section references are to `alphoryn_V_0_0.1.md`.

| Package / Module | Implements | Design Doc Reference | Spec Reference |
|---|---|---|---|
| `cli/main.py` | Entry point (`alphoryn run`); startup validation; session count display; `alphoryn status` (current run + open positions); `alphoryn history` (session table by run); skipped-session counter (FR-018) | §Core Concepts §Run Duration; §Step 1 §Wait for Candle Close | FR-001–004; FR-018; US1; SC-001; contracts/cli.md (all three commands) |
| `config/models.py` | AlphorynConfig schema, stop-loss %, all parameters | §Configuration table | FR-001; contracts/config-schema.md |
| `config/loader.py` | JSON file → CLI override resolution | §Configuration table | FR-001; contracts/cli.md |
| `scheduler/scheduler.py` | Candle boundary alignment; market hours; budget timers; triggers feedback agent for positions whose `evaluation_window_session` matches current session ordinal; owns skipped-session logic (FR-018) | §Core Concepts §Candle Close, §Session; §Step 1, §Step 2, §Step 3; §Session Workflow diagram | FR-002–005; FR-007; FR-018; SC-002; contracts/agents.md §Feedback Trigger |
| `market_data/client.py` | Internal `data_fetch` (not agent-accessible) + signal computation; exposes `build_snapshot` as sole ADK tool returning a frozen `SignalSnapshot`; 1-min bar polling for stop-loss monitor | §Data Access Pattern; §Step 5 §Resources; research.md §Paper Trading API; research.md §build_snapshot | FR-006; SC-005 |
| `memory/schema.py` | SQLAlchemy entity schema | §Memory Bank §Structure; §Write responsibilities table; data-model.md | FR-012; FR-019 |
| `memory/bank.py` | Startup position load (all `status=OPEN` positions across runs); corruption abort; per-session writes; carry-over position blocking check; write ordering on partial failure | §Memory Bank §Purpose; §Step 8 §Update Memory; §Failure Handling | FR-005; FR-012; FR-019; Clarification Q3; data-model.md §Key Invariants |
| `agents/main_agent.py` | Regime recognition per ETF; strategy selection; investigation; calls `build_snapshot` tool; outputs `SessionDecision` to execution agent; queries MemoryEntry for prior performance context | §Step 5 §Investigate §Agent tasks; §Step 6 §Decide; §Agents (Main agent row); strategies/mean_reversion.md; strategies/momentum.md; research.md §Snapshot Isolation | FR-008; FR-009; data-model.md §MemoryEntry; contracts/agents.md §Decision Handoff |
| `agents/feedback_agent.py` | Thesis vs outcome evaluation; retry policy; memory write; receives `FeedbackInput` from scheduler; extracts thesis from HTML report; uses Alpaca MCP `get_bars` for evaluation-time candle close; updates Position status to EVALUATED or EVALUATION_FAILED | §Feedback Loop (full section); §Agents (Feedback agent row); §Data Access Pattern (1H candle close row); research.md §Paper Trading API | FR-015; FR-016; FR-016a; Clarification Q1; data-model.md §FeedbackEvaluation; contracts/agents.md §Feedback Trigger |
| `agents/prompts.py` | System prompts for both agents; main agent prompt must include Snapshot Isolation enforcement clause and memory bank context format; feedback agent prompt must define thesis extraction format | §Step 5 §Resources; §Feedback Loop §Inputs; research.md §Snapshot Isolation | FR-008; FR-015; data-model.md §MemoryEntry; contracts/agents.md |
| `execution/agent.py` | ADK BaseAgent (no LLM model); Buy/Sell/Hold via Alpaca `alpaca-py` (market orders); sequential budget check via account API; determinism verified by zero model calls | §Step 7 §Execute; §Agents (Execution agent row); §Failure Handling (paper trading API, budget, market closed rows); research.md §Paper Trading API | FR-009; FR-010; Clarification Q2 |
| `monitor/monitor.py` | Stop-loss, profit target, window expiry via `alpaca-py` latest-bar polling and `close_position`; runs as background thread; writes position status to memory bank on close | §Agents (Deterministic workflow row); §Data Access Pattern (real-time price row); §Failure Handling (real-time price feed row); research.md §Real-Time Price Feed | FR-013; FR-014; SC-005; Clarification Q1; data-model.md §Position §Position States |
| `reports/generator.py` | HTML session report (per-strategy Jinja2 template); stores report path in `Session.html_report_path`; path format: `reports/run-{id}/session-{seq}.html` | §Step 8 §HTML Report; §Open Items (HTML report template) | FR-011; Clarification Q4; data-model.md §Session |
| `secrets/client.py` | Google Secret Manager key retrieval at startup | research.md §API Key Management | FR-001; quickstart.md |
| `telemetry/logger.py` | System-wide structured event emitter: all agent decisions, tool calls, execution orders, monitor triggers, and scheduler events sent to Cloud Logging as typed JSON events | research.md §Telemetry | FR-007; FR-008; FR-015 |

---

## Build Order

Modules must be built in dependency order. Blocked modules cannot be completed until their
open items are resolved (see §Open Items). Integration boundaries requiring the agent
handoff contracts are noted — see `contracts/agents.md` before implementing those modules.

### Stage 1 — Foundation (no inter-module dependencies)

1. `config/models.py` — Pydantic AlphorynConfig; no dependencies
2. `secrets/client.py` — GCP Secret Manager wrapper; no dependencies
3. `telemetry/logger.py` — Cloud Logging event emitter; no dependencies

### Stage 2 — Storage and Config Loading

4. `config/loader.py` — needs `config/models.py`
5. `memory/schema.py` — SQLAlchemy entity schema; needs `config/models.py`
6. `memory/bank.py` — needs `memory/schema.py`

### Stage 3 — Data and Execution (can be built in parallel after Stage 2)

7. `market_data/client.py` — `build_snapshot` ADK tool + price polling; needs `alpaca-py`.
   Signal fields defined in `data-model.md §ETFSignals`; computation logic from `alpaca-py`
   bars (RSI, EMA, SMA, Bollinger, MACD, volume ratio).
8. `execution/agent.py` — ADK BaseAgent; needs `memory/bank.py`, `telemetry/logger.py`.
   Requires `contracts/agents.md §Decision Handoff` before building input interface.
9. `monitor/monitor.py` — background thread; needs `memory/bank.py`, `market_data/client.py`
   (price polling only), `telemetry/logger.py`. Trailing stop mechanics defined in
   `alphoryn/strategies/momentum.md §Trailing Stop`.

### Stage 4 — Scheduling and Reporting (after Stage 3)

10. `scheduler/scheduler.py` — needs `market_data/client.py`, `memory/bank.py`,
    `telemetry/logger.py`. Feedback trigger logic requires `contracts/agents.md §Feedback
    Trigger`. Candle alignment and budget enforcement are unblocked.
11. `reports/generator.py` — Jinja2 template rendering; templates in `templates/reports/`;
    context contract in `contracts/report-context.md`.

### Stage 5 — Agents (after Stage 4)

12. `agents/prompts.py` — strategy definitions in `alphoryn/strategies/`; skills in
    `alphoryn/skills/`; Snapshot Isolation clause from `research.md §Snapshot Isolation`.
13. `agents/main_agent.py` — skills and strategy files fully authored. Requires
    `contracts/agents.md §Decision Handoff` for output interface.
14. `agents/feedback_agent.py` — templates authored; thesis extraction via
    `section#investment-thesis` (see `contracts/report-context.md §Thesis extraction`).
    Requires `contracts/agents.md §Feedback Trigger` for input interface.

### Stage 6 — CLI Integration (after all above)

15. `cli/main.py` — integrates all modules; `alphoryn status` and `alphoryn history` are
    fully unblocked; `alphoryn run` requires all prior stages.

### Threading model

The session loop runs on the main asyncio event loop. `monitor/monitor.py` runs as a
`threading.Thread` started at run startup and stopped via a `threading.Event` when the
run ends. The monitor communicates position close events by writing directly to the memory
bank (SQLite); the scheduler reads position state from the memory bank at each session
start. No inter-thread queues or events are needed beyond the stop signal.

---

## Open Items

All previously TBD design artifacts have been authored. All stages in §Build Order are
now fully unblocked (pending user refinement of strategies and skills).

| Artifact | Status | Path |
|---|---|---|
| Mean Reversion strategy | Authored | `alphoryn/strategies/mean_reversion.md` |
| Momentum strategy | Authored | `alphoryn/strategies/momentum.md` |
| Skill: identify_regime | Authored | `alphoryn/skills/identify_regime.md` |
| Skill: mean_reversion_entry | Authored | `alphoryn/skills/mean_reversion_entry.md` |
| Skill: momentum_entry | Authored | `alphoryn/skills/momentum_entry.md` |
| Skill: size_position | Authored | `alphoryn/skills/size_position.md` |
| Skill: read_memory | Authored | `alphoryn/skills/read_memory.md` |
| HTML report template: Mean Reversion | Authored | `templates/reports/mean_reversion.html.j2` |
| HTML report template: Momentum | Authored | `templates/reports/momentum.html.j2` |
| Report context contract | Authored | `contracts/report-context.md` |
| Feedback evaluation window | Resolved | Mean Reversion: +4 sessions; Momentum: +2 sessions |
