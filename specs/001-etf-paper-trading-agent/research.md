# Research: Alphoryn — Automated ETF Paper Trading System

**Phase 0 output** | **Date**: 2026-07-03 (updated 2026-07-03) | **Plan**: [plan.md](plan.md)

---

## Paper Trading API + Market Data

**Decision**: Alpaca via `alpaca-py` SDK (deterministic components) + Alpaca MCP server (LLM agents)

**Rationale**: The project owner specified Alpaca for paper trading and the Alpaca MCP server
as a tool provider for agents. Alpaca provides a unified API covering paper trading order
execution, position management, account info, historical bars, and real-time quotes in a
single integration. This replaces both ib-insync and yfinance from the initial plan.

**Market scope note**: Alpaca covers **US equities markets** (NYSE, NASDAQ, AMEX). The
original design doc referenced European exchanges (XETRA, Euronext, LSE) and EUR currency.
With Alpaca as the execution and data provider, supported ETFs are US-listed (e.g., SPY,
QQQ, EEM). The `exchange` config field is retired; market hours come from Alpaca's market
calendar API. Currency is USD for Alpaca paper accounts.

**Alternatives considered**:
- IBKR / ib-insync: Covers European exchanges but requires TWS running locally, more complex
  setup. Eliminated per project owner decision.
- yfinance: Free market data but no trading. No longer needed — Alpaca provides both.

**Integration pattern** (two layers):

*Deterministic components* (`alpaca-py` Python SDK, no MCP):
- `market_data/client.py` — fetches 1H and 1-min OHLCV bars at candle close to build
  the frozen `SignalSnapshot`; polls latest 1-min bar for stop-loss monitor
- `execution/agent.py` — places market orders; checks account/budget; cancels on failure
- `monitor/monitor.py` — polls position P&L and price; closes positions deterministically

*LLM agents* (Alpaca MCP server configured as tool provider in Google ADK):
- `agents/main_agent.py` — has `build_snapshot` as an ADK tool; calls it during
  pre-investigation to receive a frozen `SignalSnapshot`. Raw data fetching is internal to
  `market_data/client.py` — the agent never sees OHLCV bars. Once `build_snapshot` returns,
  market data tool calls are prohibited for the rest of investigation (system prompt +
  integration test enforcement; see §Snapshot Isolation).
- `agents/feedback_agent.py` — uses MCP `get_bars` to fetch the 1H candle close at
  evaluation time (design doc §Data Access Pattern: "1H candle close at evaluation time")

**Alpaca MCP server tool categories** (from https://github.com/alpacahq/alpaca-mcp-server):

Note: deterministic components (`execution/agent.py`, `monitor/monitor.py`, `scheduler/scheduler.py`,
`market_data/client.py`) use `alpaca-py` SDK directly — NOT the MCP server. The MCP server
is used only by LLM agents (main_agent, feedback_agent) via ADK tool integration.

| Category | Tools | Used via MCP by | Used via SDK by |
|---|---|---|---|
| Account & Portfolio | account info, portfolio history, activity | `agents/main_agent.py` (account context) | `execution/agent.py` (budget check) |
| Order Management | place order (market/limit/trailing-stop), cancel | — | `execution/agent.py` |
| Position Management | get positions, close position | — | `monitor/monitor.py`, `execution/agent.py` |
| Market Data | historical bars, real-time quotes, snapshots | `agents/feedback_agent.py` (evaluation-time bars) | `market_data/client.py` (signal computation + price polling) |
| Market Calendar | market clock, trading hours | — | `scheduler/scheduler.py` |
| Asset Information | asset lookup, market status | — | `config/loader.py` (ticker validation) |

**Order type**: Market order for all Buy/Sell executions at v0.0.1 (simplest; adequate for
paper trading). Trailing-stop order type available for Momentum strategy profit target in v0.1.0.

**Execution failure mode**: `alpaca-py` raises `APIError` or connection timeout → log intended
action, hold position, retry next session (design doc §Failure Handling; spec FR-017).

**Alpaca paper trading setup**: Free account at alpaca.markets; no TWS installation required.
Paper trading is the default mode (`ALPACA_PAPER_TRADE=true` in MCP config).

---

## Real-Time Price Feed (Stop-Loss Monitor)

**Decision**: Alpaca `alpaca-py` SDK — latest bar polling (≤30-second interval)

**Rationale**: `alpaca-py` provides `StockLatestBarRequest` for real-time price polling.
Same integration already required for execution — no additional dependency. Adequate for
paper trading stop-loss resolution (spec SC-005: trigger within one 1-minute candle).

**Alternative considered**: Alpaca WebSocket streaming — more precise but adds event loop
complexity. Deferred to v0.1.0.

---

## CLI Framework

**Decision**: `typer`

**Rationale**: Integrates natively with Pydantic models, generates rich help text
automatically, supports JSON config file + CLI override pattern cleanly.

**Alternatives considered**: `click` (workable, more boilerplate), `argparse` (eliminated).

---

## Configuration Loading

**Decision**: Pydantic `BaseSettings` with JSON file source + Typer CLI overrides

**Pattern**:
```
1. Load config.json (or --config path) → AlphorynConfig instance
2. Apply non-None CLI option values as overrides
3. Validate merged config → field-level error if invalid
4. Config object passed to all components; no global state
```

---

## Memory Bank Storage

**Decision**: SQLite via SQLAlchemy (`~/.alphoryn/memory.db` by default)

**Rationale**: Local database requirement. Zero-server, file-based, ACID compliant.
SQLAlchemy provides ORM and migration path. Single-process — no concurrency concerns.

**Alternatives considered**: TinyDB (weak query support), JSON files (no ACID). Both eliminated.

**Corruption / inaccessibility**: SQLAlchemy connection failure at startup → `MemoryBankError`
→ CLI prints error + exits with code 2 (spec FR-019; Clarification Q3).

---

## HTML Report Generation

**Decision**: Jinja2 with per-strategy templates in `templates/reports/`

**Template files**: `mean_reversion.html.j2`, `momentum.html.j2` — **TBD; see Open Items**.

---

## API Key Management

**Decision**: Google Secret Manager (specified by project owner)

**Secrets required**:
| Secret name (GCP) | Contents |
|---|---|
| `alphoryn-alpaca-api-key` | Alpaca paper trading API key |
| `alphoryn-alpaca-secret-key` | Alpaca paper trading secret key |

The Alpaca MCP server reads these from environment variables (`ALPACA_API_KEY`,
`ALPACA_SECRET_KEY`). `secrets/client.py` fetches them from Secret Manager at startup
and injects them as env vars before the MCP server connection is established.

GCP auth: Application Default Credentials (`gcloud auth application-default login`).

---

## Testing ADK Agents

**Decision**: Stub Google ADK responses using recorded fixtures; stub Alpaca MCP tool responses separately

**Pattern**:
- Record real ADK + MCP responses for known scenarios as JSON fixtures in `tests/fixtures/`.
- `StubGeminiClient` returns fixture for given prompt hash.
- `StubMCPClient` returns fixture for given tool name + arguments hash.
- Tests assert agent tool-calling logic and output parsing without hitting Gemini or Alpaca APIs.

**Deterministic component tests**: `execution/agent.py` and `monitor/monitor.py` tested with
`StubAlpacaClient` that returns fixed API responses for known order/position inputs.

---

## build_snapshot (Tool Architecture)

`build_snapshot` is the single ADK tool registered on the main agent for pre-investigation
data access. The agent calls it once; `market_data/client.py` handles all raw data fetching
internally via `alpaca-py` — the agent never sees OHLCV bars.

`build_snapshot` returns a frozen `SignalSnapshot` containing computed signals for both
ETFs (fields TBD; blocked on strategy md files). The agent works entirely from these
signals during investigation.

`data_fetch` is an internal function within `market_data/client.py`, not an ADK tool.
The agent has no direct access to it.

---

## Snapshot Isolation with MCP Tools (Architecture Note)

Constitution Principle V requires investigation to use only a frozen snapshot. Because the
main agent has Alpaca MCP tools available, the system prompt MUST explicitly prohibit calling
market data tools after `build_snapshot` has returned. The enforcement strategy:

1. The system prompt includes: "You have called build_snapshot and received a SignalSnapshot.
   Do not call any further market data tools during investigation. Use only the signal
   fields in the snapshot."
2. Skills (md files) reference snapshot fields by name, not MCP tool calls.
3. Integration tests assert that the main agent makes zero MCP market data tool calls during
   investigation (stubbed MCP client tracks call counts per phase).

---

## Execution Agent Architecture

**Decision**: ADK `BaseAgent` subclass with no LLM model configured

**Rationale**: The execution agent is purely deterministic — given a Buy/Sell/Hold decision
from the main agent, it performs a fixed sequence of Alpaca API calls (budget check,
order placement, confirmation). No reasoning or language model is required. ADK `BaseAgent`
provides the same ADK infrastructure (event bus, tool integration, lifecycle hooks) without
attaching a model.

**Implementation**: `execution/agent.py` subclasses `google.adk.BaseAgent` and overrides
`_run_async_impl`. It calls `alpaca-py` directly (not via MCP server) for maximum control
and testability. Unit tests mock the `alpaca-py` client and assert fixed outputs for fixed
decision inputs — satisfying constitution Principle I (Determinism).

**Why not pure Python?** Using ADK BaseAgent keeps the execution agent in the same event
and observability framework as the rest of the system (traces, lifecycle hooks, cancellation
propagation) without adding non-determinism.

---

## Telemetry

**Decision**: System-wide structured event log emitted to Cloud Logging. Every meaningful
action across all components — LLM agents, deterministic execution agent, and stop-loss
monitor — emits a structured JSON event.

**Rationale**: Full observability across the entire pipeline, not just LLM decisions.
Cloud Logging provides queryable centralized storage via GCP Logs Explorer. Events include
`latency_ms` and `session_id` on every record, enabling timing analysis and session
correlation without a separate tracing backend.

**Event log schema** — common fields on every event emitted by `telemetry/logger.py`:

| Field | Type | Description |
|---|---|---|
| `event_type` | `str` | See event types table below |
| `session_id` | `str \| None` | Parent session (`run-N/session-X`); null for run-level events |
| `component` | `str` | Emitting component (e.g., `"main_agent"`, `"execution_agent"`, `"monitor"`, `"scheduler"`) |
| `etf` | `str \| None` | ETF ticker where applicable |
| `timestamp` | `datetime` | UTC event time |
| `latency_ms` | `int \| None` | Duration where applicable |
| `payload` | `dict` | Event-specific fields (see below) |

**Event types and their payload fields**:

| Event type | Component | Key payload fields |
|---|---|---|
| `AGENT_DECISION` | `main_agent`, `feedback_agent` | `decision`, `reasoning`, `strategy`, `model_name`, `token_usage` |
| `TOOL_CALL` | any agent | `tool_name`, `tool_input`, `tool_output_summary`, `success` |
| `SIGNAL_SNAPSHOT_BUILT` | `main_agent` | `etf1_signals_summary`, `etf2_signals_summary` |
| `ORDER_PLACED` | `execution_agent` | `etf`, `side`, `qty`, `order_id` |
| `ORDER_FAILED` | `execution_agent` | `etf`, `side`, `reason` |
| `BUDGET_CHECK` | `execution_agent` | `etf`, `available_budget`, `required`, `passed` |
| `STOP_LOSS_TRIGGERED` | `monitor` | `etf`, `position_id`, `trigger_price`, `stop_loss_price` |
| `PROFIT_TARGET_TRIGGERED` | `monitor` | `etf`, `position_id`, `trigger_price`, `exit_target` |
| `WINDOW_EXPIRY_TRIGGERED` | `monitor` | `etf`, `position_id`, `session_ordinal` |
| `POSITION_CLOSED` | `monitor` | `etf`, `position_id`, `exit_reason`, `pnl` |
| `SESSION_START` | `scheduler` | `candle_close_at`, `open_positions_count` |
| `SESSION_END` | `scheduler` | `status`, `duration_ms` |
| `MARKET_CLOSED` | `scheduler` | `reason` |
| `BUDGET_TIMEOUT` | `scheduler` | `phase`, `elapsed_ms` |

GCP Logs Explorer is the primary observability UI — filter by `session_id`, `event_type`,
`component`, or `etf` to query any slice of system activity.

**Dependencies**:
- `google-cloud-logging` — upload structured JSON events to Cloud Logging

---

## Open Items

All design artifacts previously marked TBD have been authored. Subject to user refinement.

| Item | Path |
|---|---|
| Mean Reversion strategy | `alphoryn/strategies/mean_reversion.md` |
| Momentum strategy | `alphoryn/strategies/momentum.md` |
| Skills (5 files) | `alphoryn/skills/` |
| HTML report templates | `templates/reports/` |
| Report context contract | `contracts/report-context.md` |
| Feedback window timing | Mean Reversion: +4 sessions; Momentum: +2 sessions |
