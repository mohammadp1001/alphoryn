# Data Model: Alphoryn — Automated Ticker Paper Trading System

**Phase 1 output** | **Date**: 2026-07-03 | **Plan**: [plan.md](plan.md)

Design doc reference: `alphoryn_V_0_0.1.md §Memory Bank §Structure`

---

## Config Model (Pydantic — not persisted)

`AlphorynConfig` — loaded at startup, validated, passed to all components. Source of truth
for all session parameters (design doc §Configuration table; spec FR-001).

| Field | Type | Default | Notes |
|---|---|---|---|
| `ticker1` | `str` | required | Ticker symbol (e.g., `SPY`) |
| `ticker2` | `str` | required | Ticker symbol (e.g., `QQQ`) |
| `candle_timeframe` | `str` | `"1H"` | One of: `"30min"`, `"1H"`, `"4H"` |
| `run_duration` | `str` | `"24H"` | e.g., `"24H"`, `"8H"` |
| `exchange` | `str \| None` | `None` | Optional, informational only — Alpaca routes US equities automatically; market hours from Alpaca calendar API |
| `session_money_budget` | `float \| None` | `None` | USD; `None` means no budget constraint |
| `stop_loss_pct` | `float` | `0.02` | e.g., `0.02` = 2% below entry price |
| `currency` | `str` | `"USD"` | Display currency — USD for Alpaca paper accounts |
| `memory_db_path` | `str` | `"~/.alphoryn/memory.db"` | SQLite file path |

**Derived at startup** (not stored in config file):
- `session_count`: `int` = `floor(run_duration_seconds / candle_timeframe_seconds)`
- `alpaca_paper_mode`: `bool` = always `True` at v0.0.1

---

## SignalSnapshot (dataclass — not persisted)

Frozen set of computed signals returned by the `build_snapshot` ADK tool. The agent calls
`build_snapshot` and receives this object; raw market data is fetched and processed
internally by `market_data/client.py` — the agent never sees OHLCV bars. Once
`build_snapshot` returns, no further market data tool calls may occur during investigation
(Principle V: Snapshot Isolation).

| Field | Type | Notes |
|---|---|---|
| `captured_at` | `datetime` | Candle close timestamp (UTC) |
| `signals` | `dict[str, AssetSignals]` | Computed signals keyed by ticker symbol — one entry per configured ticker, not fixed to two |

**`AssetSignals` fields** (computed by `market_data/client.py` from `alpaca-py` bars):

| Field | Type | Description |
|---|---|---|
| `rsi_14` | `float` | RSI 14-period (0–100) |
| `adx_14` | `float` | Average Directional Index 14-period (0–100; >25 = trend) |
| `ema_20` | `float` | 20-period EMA price |
| `ema_50` | `float` | 50-period EMA price |
| `sma_20` | `float` | 20-period SMA price |
| `bollinger_upper` | `float` | Upper Bollinger Band (20-period, 2 std dev) |
| `bollinger_lower` | `float` | Lower Bollinger Band |
| `bollinger_pct_b` | `float` | %B: 0=lower band, 1=upper band (can exceed 0–1 range) |
| `macd_line` | `float` | EMA12 − EMA26 |
| `macd_signal` | `float` | 9-period EMA of MACD line |
| `macd_histogram` | `float` | `macd_line − macd_signal` |
| `volume_vs_avg` | `float` | Current volume / 20-period average volume |
| `current_price` | `float` | Latest close price |
| `price_vs_ema_20_pct` | `float` | `(current_price − ema_20) / ema_20 × 100` |
| `price_vs_sma_20_pct` | `float` | `(current_price − sma_20) / sma_20 × 100` |

---

## Database Entities (SQLAlchemy / SQLite)

### Run

Tracks each invocation of `alphoryn run`. Sequential run number persists the `run-N` part
of the session identity scheme (spec Clarification Q4).

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK AUTOINCREMENT` | Sequential run number |
| `started_at` | `DATETIME` | UTC |
| `ended_at` | `DATETIME \| NULL` | NULL while running |
| `config_snapshot` | `TEXT` | JSON dump of AlphorynConfig (non-secret fields only) |
| `session_count_planned` | `INTEGER` | Derived at startup |

---

### Session

One record per candle close processed. Linked to its Run.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PK` | Composite: `run-{run_id}/session-{random_seq}` (spec Clarification Q4) |
| `run_id` | `INTEGER FK → Run.id` | |
| `candle_close_at` | `DATETIME` | Candle close timestamp (UTC) |
| `created_at` | `DATETIME` | When session record was written |
| `status` | `TEXT` | `COMPLETED`, `SKIPPED_TIMEOUT`, `SKIPPED_MARKET_CLOSED`, `SKIPPED_DATA_UNAVAILABLE` |
| `html_report_path` | `TEXT \| NULL` | Relative path to HTML report file |
| `ticker_decisions` | `TEXT \| NULL` | JSON object keyed by ticker symbol, e.g. `{"SPY": {"strategy": "MEAN_REVERSION", "decision": "BUY", "execution_result": "EXECUTED"}, ...}`. One entry per ticker processed this session — supports any number of configured tickers, not just two. |
| `warnings` | `TEXT \| NULL` | JSON list of warning strings |

Per-ticker `strategy` is `MEAN_REVERSION` or `MOMENTUM`; `decision` is `BUY`, `SELL`, or `HOLD`; `execution_result` is `EXECUTED`, `SKIPPED_BUDGET`, `SKIPPED_MARKET_CLOSED`, or `SKIPPED_API_ERROR`.

---

### Position

One record per open paper trade. Ticker-scoped; the two tickers are fully independent.

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK AUTOINCREMENT` | |
| `session_id` | `TEXT FK → Session.id` | Entry session |
| `ticker` | `TEXT` | Ticker symbol |
| `strategy` | `TEXT` | `MEAN_REVERSION` or `MOMENTUM` |
| `direction` | `TEXT` | `BUY` (only Buy positions tracked; Sell closes an existing position) |
| `entry_price` | `REAL` | Execution fill price |
| `entry_time` | `DATETIME` | UTC |
| `lot_size` | `REAL` | Units / shares purchased |
| `stop_loss_price` | `REAL` | Derived: `entry_price * (1 - stop_loss_pct)` |
| `exit_target` | `TEXT` | JSON: `{"type": "price_level", "value": 123.45}` for Mean Reversion; `{"type": "trailing_stop", "trail_pct": 0.015}` for Momentum |
| `trailing_stop_high_watermark` | `REAL \| NULL` | Updated by monitor when price makes a new high; used for trailing stop computation; NULL for non-Momentum positions |
| `evaluation_window_session` | `INTEGER` | Session ordinal at which feedback agent fires. Mean Reversion: `entry_session_ordinal + 4`; Momentum: `entry_session_ordinal + 2` |
| `status` | `TEXT` | See Position States below |
| `exit_price` | `REAL \| NULL` | NULL until closed |
| `exit_time` | `DATETIME \| NULL` | NULL until closed |
| `exit_reason` | `TEXT \| NULL` | `STOP_LOSS`, `PROFIT_TARGET`, `WINDOW_EXPIRY` |

**Position States** (design doc §Step 4; spec FR-014):

```
OPEN
  → CLOSED_STOP_LOSS       (monitor: price ≤ stop_loss_price)
  → CLOSED_PROFIT_TARGET   (monitor: price reaches exit_target)
  → CLOSED_WINDOW_EXPIRY   (scheduler: evaluation window session reached)
        ↓
EVALUATED                  (feedback agent: wrote evaluation record)
EVALUATION_FAILED          (feedback agent: 3 retries exhausted — spec FR-016a)
```

---

### FeedbackEvaluation

Written by the feedback agent after comparing thesis to outcome
(design doc §Feedback Loop; spec FR-016).

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK AUTOINCREMENT` | |
| `position_id` | `INTEGER FK → Position.id` | |
| `evaluated_at` | `DATETIME` | UTC |
| `evaluation_session_id` | `TEXT FK → Session.id` | Session at which evaluation ran |
| `candle_close_price` | `REAL` | 1H candle close at evaluation time |
| `thesis_summary` | `TEXT` | Extracted from entry HTML report |
| `outcome_judgment` | `TEXT` | `CORRECT`, `INCORRECT`, `NEUTRAL` |
| `reasoning` | `TEXT` | Agent explanation |
| `attempt_count` | `INTEGER` | 1–3 (spec FR-016a retry policy) |

---

### MemoryEntry

Per-ticker, per-strategy running performance record. Queryable by the main agent during
investigation (design doc §Memory Bank §Strategy performance log).

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK AUTOINCREMENT` | |
| `ticker` | `TEXT` | Ticker symbol |
| `strategy` | `TEXT` | `MEAN_REVERSION` or `MOMENTUM` |
| `session_id` | `TEXT FK → Session.id` | |
| `decision` | `TEXT` | `BUY`, `SELL`, `HOLD` |
| `outcome_judgment` | `TEXT \| NULL` | NULL until feedback evaluated |
| `regime_context` | `TEXT` | JSON summary of market conditions at session time |
| `created_at` | `DATETIME` | |

---

## Entity Relationships

```
Run ──< Session ──< Position ──< FeedbackEvaluation
              └──< MemoryEntry
```

- One Run has many Sessions.
- One Session has zero, one, or two Positions (one per ticker, only if Buy was executed).
- One Position has zero or one FeedbackEvaluation.
- One Session has zero, one, or two MemoryEntry records (one per ticker that was processed).

---

## Key Invariants

- A Position in status `OPEN` always has a non-null `stop_loss_price` and `exit_target`.
- At most one Position per ticker may be in status `OPEN` at any time.
- A Session's `html_report_path` is non-null iff `status = COMPLETED`.
- `FeedbackEvaluation.attempt_count` is always ≤ 3; if 3 and evaluation not complete,
  parent Position moves to `EVALUATION_FAILED` and the ticker is unblocked (spec FR-016a).
- `MemoryEntry.outcome_judgment` is populated only after the linked Position has a
  `FeedbackEvaluation` record.
