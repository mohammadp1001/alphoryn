# Tasks: Alphoryn — Automated ETF Paper Trading System

**Input**: Design documents from `/specs/001-etf-paper-trading-agent/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | constitution.md ✅

**Tests**: Included — constitution Principle II mandates 100% pytest coverage (CI gate); no `pragma: no cover`.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths included in all descriptions

---

## Phase 1: Setup

**Purpose**: Project initialization and skeleton. Must complete before any module is written.

- [x] T001 Create project directory structure: `alphoryn/cli/`, `alphoryn/config/`, `alphoryn/agents/`, `alphoryn/execution/`, `alphoryn/monitor/`, `alphoryn/scheduler/`, `alphoryn/market_data/`, `alphoryn/memory/`, `alphoryn/reports/`, `alphoryn/secrets/`, `alphoryn/telemetry/`, `alphoryn/strategies/`, `alphoryn/skills/`, `tests/unit/`, `tests/integration/`, `tests/contract/`, `tests/fixtures/`, `templates/reports/`; add `__init__.py` to each Python package
- [x] T002 [P] Write `pyproject.toml` with all dependencies (`google-adk`, `alpaca-py`, `alpaca-mcp-server`, `typer`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `google-cloud-secret-manager`, `google-cloud-logging`, `jinja2`, `ruff`, `pytest`, `pytest-cov`), Ruff config (zero violations gate), and pytest-cov config (100% threshold, `--cov=alphoryn`)
- [x] T003 [P] Create `config.json` example at repo root (non-secret fields only: SPY/QQQ, `1H` timeframe, `24H` duration, USD, 2% stop-loss, no budget per `contracts/config-schema.md`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Stage 1 + Stage 2 modules from `plan.md §Build Order`. All user stories depend on these completing first.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Stage 1 — No dependencies (implement in parallel)

- [x] T004 [P] Implement `AlphorynConfig` Pydantic `BaseSettings` model in `alphoryn/config/models.py` (all fields from `data-model.md §Config Model`: `etf1`, `etf2`, `candle_timeframe`, `run_duration`, `exchange`, `session_money_budget`, `stop_loss_pct`, `max_startup_latency_seconds`, `currency`, `memory_db_path`; derived fields `session_count`, `alpaca_paper_mode`)
- [x] T005 [P] Implement `alphoryn/secrets/client.py` (fetch `alphoryn-alpaca-api-key` and `alphoryn-alpaca-secret-key` from GCP Secret Manager via Application Default Credentials; inject as `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` env vars; raise `SecretsError` on failure per `research.md §API Key Management`)
- [x] T006 [P] Implement `alphoryn/telemetry/logger.py` (system-wide structured event emitter; all 14 event types from `research.md §Telemetry`; common fields: `event_type`, `session_id`, `component`, `etf`, `timestamp`, `latency_ms`, `payload`; Cloud Logging upload via `google-cloud-logging`; on Cloud Logging unavailable: write to stderr and continue — never block execution per constitution Principle IV)

### Stage 2 — Depends on Stage 1

- [x] T007 Implement `alphoryn/config/loader.py` (layered config resolution: load JSON file at `--config` path or `./config.json`, apply non-None CLI overrides, validate merged result into `AlphorynConfig`; field-level error on invalid input; depends on T004)
- [x] T008 [P] Implement `alphoryn/memory/schema.py` (SQLAlchemy ORM models for all five entities per `data-model.md §Database Entities`: `Run`, `Session`, `Position`, `FeedbackEvaluation`, `MemoryEntry`; all columns, types, FK constraints, and `Position.status` enum values; depends on T004)
- [x] T009 Implement `alphoryn/memory/bank.py` (startup load query for all `status=OPEN` positions across all runs; raise `MemoryBankError` on inaccessible/corrupt DB; per-session writes for `Session`, `Position`, `MemoryEntry`; `FeedbackEvaluation` write + `Position.status` update; carry-over position blocking query; depends on T008)

### Unit Tests for Stage 1 + 2 (parallel after modules above)

- [x] T010 [P] Unit tests for `alphoryn/config/` in `tests/unit/test_config.py` (`AlphorynConfig` field validation, required fields, defaults, `session_count` derivation, loader JSON→CLI override resolution, invalid config raises `ValidationError`)
- [x] T011 [P] Unit tests for `alphoryn/secrets/client.py` in `tests/unit/test_secrets.py` (mock `google-cloud-secret-manager`; successful fetch injects env vars; fetch failure raises `SecretsError`)
- [x] T012 [P] Unit tests for `alphoryn/telemetry/logger.py` in `tests/unit/test_telemetry.py` (all 14 event types emit correct schema; Cloud Logging failure → stderr output, execution continues; `latency_ms` and `session_id` present on every event)
- [x] T013 Unit tests for `alphoryn/memory/` in `tests/unit/test_memory.py` (in-memory SQLite; schema integrity for all five entities; startup load returns OPEN positions from multiple runs; corrupt DB raises `MemoryBankError`; per-session write ordering; `FeedbackEvaluation.attempt_count ≤ 3` invariant)

**Checkpoint**: Foundation ready — user story implementation can begin

---

## Phase 3: User Story 1 — Configure and Launch a Trading Session (Priority: P1) 🎯 MVP

**Goal**: User runs `alphoryn run`, config is validated, session count is displayed, memory bank is loaded, and the system counts down to the next candle boundary.

**Independent Test**: Supply a valid config → confirm system reaches "waiting for candle close" state with correct session count displayed, without executing any trades (spec US1 Acceptance Scenario 1).

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T014 [P] [US1] Contract test: CLI startup output and exit codes in `tests/contract/test_cli.py` (startup banner, "N sessions planned", memory bank line, countdown line; exit code 1 on invalid config, exit code 2 on inaccessible memory bank, exit code 3 on Secret Manager unreachable; `alphoryn status` and `alphoryn history` output format — all per `contracts/cli.md`)
- [x] T015 [P] [US1] Contract test: config schema in `tests/contract/test_config_schema.py` (all required fields present; optional `session_money_budget` = None means no limit; fractional session count triggers warning; `candle_timeframe` restricted to `30min`, `1H`, `4H`; validates against `contracts/config-schema.md`)

### Implementation for User Story 1

- [x] T016 [US1] Implement candle boundary alignment and market hours check in `alphoryn/scheduler/scheduler.py` (query Alpaca market calendar API via `alpaca-py` to get next market open and candle close timestamps; compute wait time; if wait exceeds `max_startup_latency_seconds` emit warning and proceed; display countdown to stdout)
- [x] T017 [US1] Implement `alphoryn run` startup path in `alphoryn/cli/main.py` (Typer app; load config via `config/loader.py`; fetch secrets via `secrets/client.py`; load memory bank open positions via `memory/bank.py`; compute `session_count`; warn on fractional sessions; display startup output per `contracts/cli.md`; pass control to scheduler)
- [x] T018 [US1] Implement `alphoryn status` command in `alphoryn/cli/main.py` (query memory bank for current run + open positions; display format per `contracts/cli.md`; `--db` path option)
- [x] T019 [US1] Implement `alphoryn history` command in `alphoryn/cli/main.py` (query memory bank sessions by run; `--run` filter; `--db` path option; display table most-recent-first per `contracts/cli.md`)
- [x] T020 [US1] Integration test: full startup cycle in `tests/integration/test_startup.py` (stub `alpaca-py` calendar API + stub Secret Manager; valid config → reaches waiting state, session count matches; fractional session count → warning emitted; invalid config → exit code 1; missing memory bank → exit code 2; Secret Manager unreachable → exit code 3)

**Checkpoint**: User Story 1 fully functional — `alphoryn run/status/history` all respond correctly

---

## Phase 4: User Story 2 — Autonomous Per-Session Decision Cycle (Priority: P1) 🎯 MVP

**Goal**: At each candle close, the system investigates both ETFs, selects a strategy per ETF, decides Buy/Sell/Hold per ETF, executes via Alpaca, generates an HTML report, and writes a memory bank entry.

**Independent Test**: Trigger one candle close → system completes the full investigate-decide-execute cycle → session record + HTML report + memory bank entry written, without requiring a second candle close (spec US2 acceptance scenarios).

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T021 [P] [US2] Unit tests for `alphoryn/market_data/client.py` in `tests/unit/test_market_data.py` (stub `alpaca-py` bars; verify all 15 `ETFSignals` fields computed correctly from fixture OHLCV data: RSI-14, ADX-14, EMA-20, EMA-50, SMA-20, Bollinger bands and %B, MACD line/signal/histogram, volume ratio, price vs EMA/SMA pct; `build_snapshot` returns frozen `SignalSnapshot`; `data_fetch` not exposed as ADK tool)
- [x] T022 [P] [US2] Unit tests for `alphoryn/execution/agent.py` in `tests/unit/test_execution.py` (stub `alpaca-py`; BUY decision → `BUDGET_CHECK` + `ORDER_PLACED` events + `Position` written; HOLD → `AGENT_DECISION` event only; budget exceeded → `ORDER_FAILED`; assert zero LLM model calls — verifies constitution Principle I)
- [x] T023 [P] [US2] Unit tests for `alphoryn/reports/generator.py` in `tests/unit/test_reports.py` (mean_reversion template renders `<section id="investment-thesis">`; momentum template renders trailing stop watermark field; path format `reports/run-{id}/session-{seq}.html`; per-strategy context object from `contracts/report-context.md`)

### Implementation for User Story 2

- [x] T024 [US2] Implement `alphoryn/market_data/client.py` (internal `data_fetch` using `alpaca-py` `StockBarsRequest` for 1H bars; compute all 15 `ETFSignals` fields from OHLCV bars; `build_snapshot` registered as ADK tool returning frozen `SignalSnapshot` for both ETFs; separate 1-min bar polling method for stop-loss monitor; `data_fetch` not exposed to agents — internal only per `research.md §build_snapshot`)
- [x] T025 [US2] Implement `alphoryn/agents/prompts.py` main agent system prompt (regime recognition instructions; strategy selection rules referencing `alphoryn/strategies/mean_reversion.md` and `alphoryn/strategies/momentum.md`; snapshot isolation enforcement clause: "Do not call any further market data tools after build_snapshot returns"; memory bank context format; output schema for `SessionDecision` per `contracts/agents.md §Decision Handoff`)
- [x] T026 [US2] Implement `alphoryn/agents/main_agent.py` (Google ADK `LlmAgent` with Gemini model; `build_snapshot` registered as sole ADK tool; regime recognition per ETF using `alphoryn/skills/` (identify_regime, mean_reversion_entry, momentum_entry, size_position, read_memory); outputs `SessionDecision` dataclass per `contracts/agents.md`; emits `AGENT_DECISION` + `TOOL_CALL` + `SIGNAL_SNAPSHOT_BUILT` telemetry events)
- [ ] T027 [US2] Implement `alphoryn/execution/agent.py` (ADK `BaseAgent` subclass — no LLM model configured; `_run_async_impl` processes `SessionDecision` sequentially per ETF per `contracts/agents.md §Decision Handoff`: HOLD → log; BUY/SELL → budget check via `alpaca-py` → `BUDGET_CHECK` event → market order via `alpaca-py` → `ORDER_PLACED`/`ORDER_FAILED` event → write `Position` to memory bank with `status=OPEN`; existing OPEN position blocks new BUY per FR-014)
- [ ] T028 [US2] Implement `alphoryn/reports/generator.py` (Jinja2 template rendering using `templates/reports/mean_reversion.html.j2` and `templates/reports/momentum.html.j2`; context object per `contracts/report-context.md`; output path: `reports/run-{run_id}/session-{session_seq}.html`; store path in `Session.html_report_path`; `<section id="investment-thesis">` present for feedback agent extraction)
- [ ] T029 [US2] Implement session budget enforcement and heartbeat in `alphoryn/scheduler/scheduler.py` (`asyncio.wait_for` with 52-min limit for investigation phase; 7-min limit for decide+execute phase; overrun → force Hold on all ETFs + emit `BUDGET_TIMEOUT` telemetry; 5-min heartbeat stdout lines during investigation: `[session-id] investigating... N min elapsed`; emit `SESSION_START` + `SESSION_END` telemetry)
- [ ] T030 [US2] Implement full session loop in `alphoryn/scheduler/scheduler.py` (outer run loop: check run complete + market open; inner session: wait for candle close → invoke main_agent → pass `SessionDecision` to execution_agent → generate HTML report → write `Session` + `MemoryEntry` records; skipped sessions not counted against total per FR-018; emit `MARKET_CLOSED` telemetry on closed market)
- [ ] T031 [US2] Integration test: single session cycle in `tests/integration/test_session_cycle.py` (StubGeminiClient returns fixture `SessionDecision`; StubMCPClient returns fixture signal data; StubAlpacaClient returns fixture bars + order confirmation; assert zero MCP market data calls during investigation phase; assert `Session` record written + `html_report_path` non-null + `MemoryEntry` written; investigation timeout → Hold forced + `BUDGET_TIMEOUT` event emitted)

**Checkpoint**: User Stories 1 AND 2 both work independently — full investigation-to-report cycle functional

---

## Phase 5: User Story 3 — Position Lifecycle and Risk Management (Priority: P2)

**Goal**: Open positions are continuously monitored; stop-loss, profit-target, and evaluation-window exits trigger automatically without LLM involvement; main agent is blocked from opening new positions on an ETF with an open unevaluated trade.

**Independent Test**: Open a simulated position → price hits stop-loss threshold → position closes automatically and is logged → main agent attempt to BUY same ETF is forced to Hold (spec US3 acceptance scenarios).

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T032 [P] [US3] Unit tests for `alphoryn/monitor/monitor.py` in `tests/unit/test_monitor.py` (StubAlpacaClient; stop-loss price breach → `STOP_LOSS_TRIGGERED` + `POSITION_CLOSED` events + `Position.status = CLOSED_STOP_LOSS`; price reaches `exit_target` price level → `PROFIT_TARGET_TRIGGERED`; `evaluation_window_session` reached → `WINDOW_EXPIRY_TRIGGERED`; Momentum trailing stop: new price high updates `trailing_stop_high_watermark`; stop_price = watermark × (1 − trail_pct); zero LLM calls asserted)

### Implementation for User Story 3

- [ ] T033 [US3] Implement `alphoryn/monitor/monitor.py` (subclass `threading.Thread`; polls latest 1-min bar via `alpaca-py` every ≤30 seconds per SC-005; for each OPEN position: check stop-loss breach (`current_price ≤ stop_loss_price`), profit-target reach (price level or trailing stop), window expiry (`evaluation_window_session == current_session_ordinal`); on exit: call `alpaca-py` `close_position` → on success write `Position.exit_price/exit_time/exit_reason/status`; update `trailing_stop_high_watermark` for Momentum positions on new price highs; emit `STOP_LOSS_TRIGGERED`/`PROFIT_TARGET_TRIGGERED`/`WINDOW_EXPIRY_TRIGGERED` + `POSITION_CLOSED` telemetry; on `close_position` failure retry next poll; stopped via `threading.Event`; thread stays alive while any position is OPEN after run ends per `contracts/agents.md §Monitor Lifecycle`)
- [ ] T034 [US3] Implement OPEN-position blocking in `alphoryn/execution/agent.py` (before executing BUY for an ETF: query memory bank for OPEN position on same ETF ticker; if found emit `AGENT_DECISION` HOLD with reason "position-blocked" and skip order; ETF2 unaffected when ETF1 is blocked per US3 Acceptance Scenario 3)
- [ ] T035 [US3] Integration test: position lifecycle in `tests/integration/test_position_lifecycle.py` (open BUY position via StubAlpacaClient; simulate price drop to stop-loss → monitor closes position, status = `CLOSED_STOP_LOSS`; assert same ETF BUY in next session blocked; simulate Momentum price rise → trailing stop watermark updated; window expiry → `CLOSED_WINDOW_EXPIRY`)

**Checkpoint**: User Stories 1, 2, AND 3 all independently functional — risk management in place

---

## Phase 6: User Story 4 — Feedback Evaluation and Memory Learning (Priority: P2)

**Goal**: At the strategy-defined evaluation window, the feedback agent compares the original thesis to the actual outcome, writes a structured judgment to the memory bank, and unblocks the ETF for new trades.

**Independent Test**: Simulate a completed trade entry, fast-forward to the evaluation session, confirm feedback agent produces a `FeedbackEvaluation` record in memory bank and marks position `EVALUATED` (spec US4 acceptance scenarios).

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T036 [P] [US4] Unit tests for `alphoryn/agents/feedback_agent.py` in `tests/unit/test_feedback_agent.py` (StubGeminiClient; thesis extraction from HTML `<section id="investment-thesis">`; `CORRECT`/`INCORRECT`/`NEUTRAL` judgment written to `FeedbackEvaluation`; `Position.status = EVALUATED`; 3-retry policy: first two fail → retry; third fail → `EVALUATION_FAILED`, ETF unblocked; `MemoryEntry.outcome_judgment` populated after evaluation)

### Implementation for User Story 4

- [ ] T037 [US4] Implement `alphoryn/agents/prompts.py` feedback agent system prompt (thesis extraction instructions: parse `<section id="investment-thesis">` from HTML; judgment rubric: `CORRECT` if outcome aligns with thesis, `INCORRECT` if contradicts, `NEUTRAL` if insufficient evidence; output schema for `FeedbackEvaluation` record; retry instructions)
- [ ] T038 [US4] Implement `alphoryn/agents/feedback_agent.py` (Google ADK `LlmAgent` with Gemini model; receives `FeedbackInput` from scheduler per `contracts/agents.md §Feedback Trigger`; step 1: read HTML report at `html_report_path` → extract thesis from `<section id="investment-thesis">`; step 2: fetch 1H candle close at evaluation time via Alpaca MCP `get_bars`; step 3: produce `CORRECT`/`INCORRECT`/`NEUTRAL` judgment; step 4: write `FeedbackEvaluation` + update `Position.status = EVALUATED` + write `MemoryEntry.outcome_judgment`; retry policy: up to 3 attempts; on 3rd failure: write partial `FeedbackEvaluation`, set `Position.status = EVALUATION_FAILED`, unblock ETF, emit warning telemetry; emit `AGENT_DECISION` telemetry with reasoning)
- [ ] T039 [US4] Implement feedback trigger in `alphoryn/scheduler/scheduler.py` (at start of each session, before investigation: query memory bank for positions where `status IN (CLOSED_STOP_LOSS, CLOSED_PROFIT_TARGET, CLOSED_WINDOW_EXPIRY)` AND `evaluation_window_session == current_session_ordinal` AND no `FeedbackEvaluation` exists; build `FeedbackInput` from Position + Session records; invoke `feedback_agent` sequentially for each due position; evaluation runs before investigation in same session per `contracts/agents.md §Feedback Trigger`)
- [ ] T040 [US4] Integration test: feedback evaluation cycle in `tests/integration/test_feedback.py` (StubGeminiClient + StubMCPClient; open position → position closes → evaluation window session arrives → scheduler triggers feedback_agent → `FeedbackEvaluation` written with `outcome_judgment` + `Position.status = EVALUATED` → ETF unblocked for new BUY; simulate 3 consecutive feedback failures → `EVALUATION_FAILED` + ETF unblocked)

**Checkpoint**: All four user stories independently functional — full learning loop operational

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: CI gates, coverage verification, and quickstart validation.

- [ ] T041 [P] Ruff linting pass: run `ruff check alphoryn/ tests/` and fix until zero violations; verify `ruff.toml` or `pyproject.toml [tool.ruff]` config is consistent with CI gate
- [ ] T042 [P] pytest coverage pass: run `pytest --cov=alphoryn --cov-report=term-missing` and verify 100% coverage on all modules; fix any uncovered lines (no `pragma: no cover` allowed per constitution Principle II)
- [ ] T043 Quickstart validation: follow `quickstart.md` end-to-end; verify `alphoryn --help`, `alphoryn run --help`, `alphoryn status --help`, `alphoryn history --help` all respond; verify config.json example loads without error; confirm memory bank initializes at `~/.alphoryn/memory.db`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — **BLOCKS all user stories**
- **User Story 1 (Phase 3)**: Depends on Phase 2 completion — no dependency on US2/US3/US4
- **User Story 2 (Phase 4)**: Depends on Phase 2 completion — no dependency on US1 (except CLI integration which can be wired last)
- **User Story 3 (Phase 5)**: Depends on Phase 2 completion — `monitor/monitor.py` also needs `market_data/client.py` from Phase 4 (T024)
- **User Story 4 (Phase 6)**: Depends on Phase 2 + `reports/generator.py` (T028 from Phase 4)
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

| Story | Depends on | Blocking |
|---|---|---|
| US1 (P1) | Phase 2 | Nothing blocked on US1 |
| US2 (P1) | Phase 2 | US3 needs `market_data/client.py` (T024); US4 needs `reports/generator.py` (T028) |
| US3 (P2) | Phase 2 + T024 | US4 benefit from US3 (positions close before feedback) |
| US4 (P2) | Phase 2 + T028 | Nothing blocked on US4 |

### Within Each User Story

- Tests → Models → Services → Integration (write tests first, verify they fail)
- `agents/prompts.py` (T025 for US2, T037 for US4) before the agent implementation it describes
- Foundation unit tests (T010–T013) can run in parallel once corresponding modules exist
- Models before services, services before integration tests

### Parallel Opportunities

```bash
# Phase 2 Stage 1 — full parallel:
Task T004: AlphorynConfig in alphoryn/config/models.py
Task T005: secrets/client.py
Task T006: telemetry/logger.py

# Phase 2 unit tests — full parallel (after Stage 2 complete):
Task T010: tests/unit/test_config.py
Task T011: tests/unit/test_secrets.py
Task T012: tests/unit/test_telemetry.py
Task T013: tests/unit/test_memory.py

# US2 tests — full parallel (before implementation):
Task T021: tests/unit/test_market_data.py
Task T022: tests/unit/test_execution.py
Task T023: tests/unit/test_reports.py

# Polish — full parallel:
Task T041: ruff check alphoryn/ tests/
Task T042: pytest --cov=alphoryn
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (**CRITICAL — blocks all stories**)
3. Complete Phase 3: User Story 1 (configure + launch)
4. **STOP and VALIDATE**: `alphoryn run` reaches "waiting for candle close" state
5. Complete Phase 4: User Story 2 (session decision cycle)
6. **STOP and VALIDATE**: single candle close → full session cycle → HTML report generated
7. Deploy/demo the MVP

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ready
2. Phase 3 (US1) → `alphoryn run/status/history` all functional
3. Phase 4 (US2) → full session cycle with investigation + execution + report
4. Phase 5 (US3) → position monitoring + risk management active
5. Phase 6 (US4) → feedback evaluation closes the learning loop
6. Phase 7 → CI green (100% coverage + zero ruff violations)

### Parallel Team Strategy

Once Phase 2 is complete:
- **Developer A**: Phase 3 (US1) — config, CLI, scheduler candle alignment
- **Developer B**: Phase 4 (US2) — market_data, agents, execution, reports
- **Developer C**: Phase 5 (US3) — monitor, position blocking
- Developer A resumes Phase 6 (US4) after Phase 3 is done

---

## Notes

- `[P]` = tasks touch different files with no incomplete-task dependencies; safe to run in parallel
- `[Story]` label maps to spec.md user story for traceability
- Tests MUST be written and verified to FAIL before corresponding implementation
- Constitution Principle II: 100% coverage is a CI hard gate — no `pragma: no cover`
- Constitution Principle I: `execution/agent.py` and `monitor/monitor.py` must contain zero LLM model calls; assert in unit tests
- Constitution Principle V: main agent must make zero MCP market data calls after `build_snapshot` returns; assert in integration tests (T031) via stubbed MCP call-count tracking
- Commit after each task or logical group; run `ruff check` + `pytest` before each commit
- Stop at Phase 3 and Phase 4 checkpoints to validate stories independently before proceeding
