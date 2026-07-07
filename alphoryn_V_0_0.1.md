# alphoryn V_0.0.1

> **Status**: Implemented — all 43 tasks complete, 440 tests, 100% coverage, CI green.
> Last updated: 2026-07-07

---

## Overview

An agentic system for automated ETF paper trading using LLM-assisted discretionary
decision-making. The system reasons over available resources within a time-and-money-budgeted
session and executes decisions via a deterministic execution agent.

**Technology stack**: Python 3.13+ · Google ADK + Gemini · Alpaca paper trading ·
SQLite (SQLAlchemy) · Typer CLI · Google Cloud (Secret Manager, Cloud Logging, Cloud Trace)

---

## Configuration

| Parameter | Type | Default | Notes |
|---|---|---|---|
| Mode | — | Paper trading only | Alpaca paper environment |
| `tickers` | `list[str]` | required (min 2) | US-listed symbols, e.g. `["SPY", "QQQ"]` |
| `candle_timeframe` | string | `1H` | `10min`, `30min`, `1H`, `4H` |
| `run_duration` | string | `24H` | Clock time, e.g. `10min`, `24H` |
| `extended_hours` | bool | `false` | Include pre/post-market sessions |
| `currency` | string | `USD` | All amounts in USD |
| `stop_loss_pct` | float | — | e.g. `0.02` = 2% |
| `session_money_budget` | float \| null | `null` | Null = no limit |
| `max_startup_latency_seconds` | int | `60` | Warn and proceed if wait exceeds this |
| `memory_db_path` | string | `~/.alphoryn/memory.db` | SQLite file path |

**API credentials** are stored in Google Secret Manager — never in config files or the repo:

| Secret name | Injected as |
|---|---|
| `alpaca-api-key` | `ALPACA_API_KEY` |
| `alpaca-api-secret` | `ALPACA_SECRET_KEY` |

GCP auth uses Application Default Credentials (ADC). Project: `alphoryn`.

**Market scope**: Alpaca covers US equities (NYSE, NASDAQ, AMEX). Tickers must be
US-listed. Market hours come from Alpaca's market calendar API — no exchange config needed.

---

## Core Concepts

### Candle Timeframe
The resolution of market data the strategy reads. Supported: `10min`, `30min`, `1H`, `4H`.
Each candle covers one period of price action (Open / High / Low / Close).

### Candle Close
The moment a candle's time period ends and its final price is locked. This event
**triggers each session**. Candles close on fixed boundaries determined by the configured
timeframe and Alpaca's market calendar.

### Session
A single atomic decision unit — one candle close, one investigation, one action per ticker.
The system always aligns to market candle boundaries, not to the system start time.

> If the system starts at 11:47 ET with a 1H timeframe, it waits until 12:00 ET for the
> first candle close. The wait time is displayed with a live countdown.

### Run Duration
User-defined in clock time (default: 24H). The system derives the session count at startup:

> `sessions = run_duration / candle_timeframe` (rounded down)

| Run duration | Candle timeframe | Sessions |
|---|---|---|
| 24H | 1H | 24 |
| 24H | 4H | 6 |
| 10min | 10min | 1 |
| 24H | 30min | 48 |

**Fractional session warning:** If the division does not produce a whole number, the system
warns the user at startup and rounds down. Adjust run duration or candle timeframe to produce
a clean result.

---

## CLI Commands

```
alphoryn run [--config PATH] [--timeframe TIMEFRAME] [--duration DURATION]
alphoryn status [--db PATH]
alphoryn history [--run RUN_ID] [--db PATH]
```

Startup banner example:
```
Tickers: SPY, QQQ | Timeframe: 10min | Duration: 10min
Sessions planned: 1
Memory bank: 0 open positions
[run-3/session-0001] SESSION START  candle=12:30 UTC
[run-3/session-0001] DECISION  SPY: HOLD (MEAN_REVERSION)  |  QQQ: BUY (MEAN_REVERSION)
[run-3/session-0001] Report -> reports\run-3\run-3\session-0001.html
[run-3/session-0001] Memory written  SPY=HOLD  QQQ=BUY
[run-3/session-0001] SESSION END  status=COMPLETED
```

---

## Session Workflow

```
wait for candle close
    -> check run duration
    -> check market hours
    -> check open positions / trigger pending feedback
    -> investigate (per ticker, in parallel)
    -> decide (per ticker)
    -> execute (per ticker, deterministic)
    -> write HTML report
    -> update memory bank
[strategy-defined window after entry]
    -> feedback agent (per ticker with closed position)
```

### Time Budget per Session

Every session must complete within one candle timeframe.

| Step | Budget |
|---|---|
| Check run duration + market hours + open positions | ~1 min |
| Investigate | ~52 min |
| Decide + Execute | ~7 min |

Memory update and report generation run after execution, outside the budget.
Feedback agent runs at the start of the strategy-defined evaluation session.

---

## Step Definitions

### 1. Wait for Candle Close
System is idle until the next candle boundary. The wait time is displayed as a live
countdown. If the wait exceeds `max_startup_latency_seconds`, a warning is emitted and
the system proceeds anyway.

### 2. Check Run Duration
Verify the run has not completed. Session count is derived at startup.

- Current session < derived session count → proceed
- Current session = derived session count → log completion, exit

Timed-out sessions are skipped and do not count toward the total.

### 3. Check Market Hours
Query Alpaca market calendar API.

- Market open → proceed
- Market closed → log with timer, wait for next open

### 4. Check Open Positions / Feedback Trigger
Per ticker, query memory bank for positions where the evaluation window has arrived.
Invoke the feedback agent for each due position before investigation begins.

- No open position → main agent free to decide Buy / Sell / Hold
- Open position, not yet evaluated → main agent forced to Hold on that ticker
- Open position, evaluated → main agent free again

Tickers are independent — a blocked ticker does not affect others.

### 5. Investigate
The main agent calls `build_snapshot` (the sole registered ADK tool) once. This returns
a frozen `SignalSnapshot` containing all 15 technical signals for all tickers. After
`build_snapshot` returns, no further market data tool calls are permitted (Principle V).

**15 signals per ticker (from `alphoryn/market_data/client.py`):**
RSI-14, ADX-14, EMA-20, EMA-50, SMA-20, Bollinger upper/lower/%B,
MACD line/signal/histogram, volume vs avg, current price, price vs EMA-20 pct,
price vs SMA-20 pct.

**Agent tasks (per ticker):**
1. Regime recognition — identify which strategy fits current conditions (Mean Reversion or Momentum)
2. Signal execution — apply strategy rules to generate a decision
3. Lot sizing — determine order size within the session money budget
4. Profit target — set a trade-specific exit target

**Timeout rule:** If investigation exceeds its budget, the system forces Hold on all
tickers and emits a `BUDGET_TIMEOUT` telemetry event.

### 6. Decide
The main agent outputs a `SessionDecision` containing one `AssetDecision` per ticker.
Each has: `ticker`, `action` (Buy/Sell/Hold), `strategy`, `lot_size`, `exit_target`,
`reasoning`. Each ticker may have a different strategy and different action.

### 7. Execute
The execution agent (deterministic, no LLM) processes each `AssetDecision`:

- Hold → log, no order
- Buy/Sell → budget check → market order via Alpaca → write `Position(status=OPEN)`
- Existing open position on same ticker → force Hold ("position-blocked")
- Budget exceeded → skip order, log warning

Stop-loss threshold is from config. Profit target is set by the main agent per trade.
Both are enforced by the deterministic monitor thread (not the execution agent).

### 8. HTML Report + Memory Update
After execution, the scheduler:
1. Renders `templates/reports/session.html.j2` using the unified template (all tickers
   in one report, per-ticker decisions table + reasoning sections)
2. Writes `Session` + `MemoryEntry` records to the memory bank
3. Emits `SESSION_END` telemetry

Report path: `reports/run-{run_id}/{session_seq}.html`

---

## Memory Bank

SQLite database at `memory_db_path` (default `~/.alphoryn/memory.db`), managed via
SQLAlchemy ORM. Initialized fresh if missing; **hard abort** if inaccessible or corrupt.

### Schema (5 entities)

| Entity | Key fields |
|---|---|
| `Run` | `run_id`, `started_at`, `config_snapshot` |
| `Session` | `session_id`, `run_id`, `candle_close_at`, `html_report_path`, `status` |
| `Position` | `ticker`, `entry_price`, `lot_size`, `stop_loss_price`, `exit_target`, `status`, `trailing_stop_high_watermark` |
| `FeedbackEvaluation` | `position_id`, `outcome_judgment` (CORRECT/INCORRECT/NEUTRAL), `attempt_count` |
| `MemoryEntry` | `ticker`, `strategy`, `decision`, `outcome_judgment`, `session_ref` |

### Write responsibilities

| Writer | What they write |
|---|---|
| Main agent | `Session`, `MemoryEntry` (strategy, decision, reasoning, regime context) |
| Execution agent | `Position(status=OPEN)` on BUY/SELL execution |
| Monitor thread | `Position` exit fields (exit_price, exit_time, exit_reason, status) |
| Feedback agent | `FeedbackEvaluation`, `Position.status = EVALUATED`, `MemoryEntry.outcome_judgment` |

### Cross-run carry-over
Open positions persist across runs. On startup, the system loads all `status=OPEN`
positions from the memory bank, applies position-blocking rules immediately, and the
monitor thread resumes stop-loss polling at market open.

---

## Feedback Loop

Triggered at a strategy-defined evaluation window after the entry session (not a fixed
schedule). Each ticker is evaluated independently.

| Strategy | Evaluation window |
|---|---|
| Momentum | 1–2 sessions after entry |
| Mean Reversion | 3–6 sessions after entry |

**Workflow:**
```
at start of evaluation session (before investigation)
    -> read HTML report from entry session
    -> parse <section id="investment-thesis"> for original reasoning
    -> fetch 1H candle close at evaluation time via Alpaca
    -> compare thesis vs outcome
    -> write FeedbackEvaluation (CORRECT / INCORRECT / NEUTRAL)
    -> update Position.status = EVALUATED
    -> unblock ticker for new trades
```

**Retry policy:** Up to 3 attempts. On 3rd consecutive failure: write partial evaluation,
set `Position.status = EVALUATION_FAILED`, unblock ticker, log warning.

**Role:** Evaluator only. The feedback agent does not manage positions or trigger execution.

---

## Position Monitor

Runs as a background thread (`threading.Thread`) alongside the session loop.

- Polls latest 1-minute bar via Alpaca every ≤30 seconds
- Per open position: checks stop-loss breach, profit-target reach, evaluation-window expiry
- On exit trigger: calls `alpaca-py` `close_position` → writes exit fields to `Position`
- Momentum trailing stop: updates `trailing_stop_high_watermark` on new price highs;
  stop price = watermark × (1 − trail_pct)
- On `close_position` failure: retries on next poll
- Thread stays alive while any position remains OPEN after the run ends

---

## Telemetry

Two independent streams run in parallel:

### Stream 1 — Structured Events (Cloud Logging)

`alphoryn/telemetry/logger.py` → `TelemetryLogger` emits typed JSON events to
GCP Cloud Logging under log name `alphoryn`.

**14 event types:**
`AGENT_DECISION`, `TOOL_CALL`, `SIGNAL_SNAPSHOT_BUILT`, `ORDER_PLACED`, `ORDER_FAILED`,
`BUDGET_CHECK`, `STOP_LOSS_TRIGGERED`, `PROFIT_TARGET_TRIGGERED`, `WINDOW_EXPIRY_TRIGGERED`,
`POSITION_CLOSED`, `SESSION_START`, `SESSION_END`, `MARKET_CLOSED`, `BUDGET_TIMEOUT`

**Common fields:** `event_type`, `session_id`, `component`, `etf` (ticker), `timestamp`,
`latency_ms`, `payload`

**Fallback:** If Cloud Logging is unavailable, events are written to stderr. A logging
failure never blocks or aborts execution (Principle IV).

**Querying:**
```
logName="projects/alphoryn/logs/alphoryn"
jsonPayload.event_type="AGENT_DECISION"
```

### Stream 2 — OTel Traces (Cloud Trace + Cloud Logging)

`alphoryn/telemetry/otel.py` → `setup_otel()` wires up Google ADK's built-in GCP exporters.
Called once at CLI startup before any agent is initialized.

- Each `InMemoryRunner.run()` call (one per candle for MainAgent, one per closed position
  for FeedbackAgent) becomes a root span in Cloud Trace
- Each Gemini API call is a child span (model name, token counts, latency)
- `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` (default) — full prompt and
  response text included in span attributes
- Service name: `alphoryn`

**Querying:**
Console → Trace → Trace List → filter by Service name `alphoryn`

> **Note:** Requires `opentelemetry-exporter-gcp-*` packages. If missing, OTel setup fails
> silently and traces are not exported. Stream 1 (Cloud Logging) is unaffected.

---

## Agents

| Agent | Type | Responsibility |
|---|---|---|
| `MainAgent` | ADK `LlmAgent` (Gemini) | Calls `build_snapshot` tool; outputs `SessionDecision` with one `AssetDecision` per ticker; emits `AGENT_DECISION` + `TOOL_CALL` + `SIGNAL_SNAPSHOT_BUILT` telemetry |
| `ExecutionAgent` | ADK `BaseAgent` (no LLM) | Processes `SessionDecision` per ticker; budget check + market order via `alpaca-py`; writes `Position`; emits `BUDGET_CHECK` + `ORDER_PLACED`/`ORDER_FAILED` telemetry |
| `FeedbackAgent` | ADK `LlmAgent` (Gemini) | Evaluates thesis vs outcome; writes `FeedbackEvaluation`; 3-retry policy; emits `AGENT_DECISION` telemetry |
| Monitor | `threading.Thread` (deterministic) | Polls 1-min bars; stop-loss / profit-target / window-expiry exits; updates `Position`; emits `STOP_LOSS_TRIGGERED` / `PROFIT_TARGET_TRIGGERED` / `WINDOW_EXPIRY_TRIGGERED` / `POSITION_CLOSED` |

---

## Data Access Pattern

| Data | When fetched | Who uses it |
|---|---|---|
| 1H + 1-min candles | Session start (inside `build_snapshot`) | Main agent (frozen snapshot) |
| 1-min bars | Every ≤30 sec, continuous | Monitor thread only |
| 1H candle close | At feedback evaluation time | Feedback agent |
| Market calendar | Session start | Scheduler (candle alignment, market hours) |

---

## Failure Handling

| Failure | Behavior |
|---|---|
| Fractional session count at startup | Warn user, round down, suggest config adjustment |
| Startup wait exceeds `max_startup_latency_seconds` | Warn user, proceed anyway |
| Market closed at execution time | Skip execution, log warning |
| Investigation budget exceeded (52 min) | Force Hold on all tickers, emit `BUDGET_TIMEOUT` |
| Session money budget exceeded | Skip execution, log warning |
| Market data API unavailable | Force Hold, log warning, skip session (not counted) |
| Real-time price feed unavailable | Suspend monitor, alert user, resume when restored |
| Paper trading API unavailable | Log intended action, skip execution, Hold, retry next session |
| Feedback evaluation failure (≤3 retries) | Retry immediately |
| Feedback evaluation failure (>3 retries) | Mark `EVALUATION_FAILED`, unblock ticker, log warning |
| Cloud Logging unavailable | Fall back to stderr, never block execution |
| OTel exporter missing | Fail silently, traces not exported, execution unaffected |
| Memory bank inaccessible / corrupt | Hard abort with error (exit code 2) |
| Secret Manager unreachable | Hard abort with error (exit code 3) |
