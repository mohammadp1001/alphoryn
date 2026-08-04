# Agent Integration Contracts: Alphoryn

**Phase 1 output** | **Date**: 2026-07-05 | **Plan**: [../plan.md](../plan.md)

Documents the data structures and protocols at the three internal integration boundaries
where components hand off control or data to each other. These are not persisted to the
memory bank — they are in-process Python objects.

---

## Decision Handoff (`main_agent` → `execution/agent.py`)

After investigation, `main_agent` produces a `SessionDecision` containing one `AssetDecision`
per ticker, in a list (supports any number of configured tickers, not just two). This object
is passed directly to `execution/agent.py` as a Python dataclass.

```python
@dataclass(frozen=True)
class AssetDecision:
    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    strategy: Literal["MEAN_REVERSION", "MOMENTUM"] | None
    lot_size: int | None        # shares; None if action is SELL or HOLD
    exit_target: dict | None    # None if action is not BUY
    reasoning: str              # emitted to telemetry; not stored in DB

@dataclass(frozen=True)
class SessionDecision:
    session_id: str
    decisions: list[AssetDecision]
```

`exit_target` format matches `Position.exit_target` in data-model.md:
- Mean Reversion: `{"type": "price_level", "value": 123.45}`
- Momentum: `{"type": "trailing_stop", "trail_pct": 0.015}`

**Execution sequence in `execution/agent.py`** (per ticker, sequential, via `execute()` iterating `decision.decisions`):
1. If action is HOLD: skip
2. If an existing `OPEN` position exists for the same ticker: force HOLD (position-blocked, FR-014)
3. Budget check via `alpaca-py` account API
4. If budget insufficient: skip the ticker's order
5. Place market order via `alpaca-py`
6. On success: write `Position` record to memory bank with `status=OPEN`

**Known gap**: unlike `main_agent`, `monitor`, and `feedback_agent`, `execution/agent.py`
does not currently have a `TelemetryLogger` wired in and emits no telemetry events
(`ORDER_PLACED`/`ORDER_FAILED`/`BUDGET_CHECK`, though declared in `telemetry/logger.py`'s
`EVENT_TYPES`, are never emitted in the current implementation). See research.md
§Telemetry for the full known-gap note.

---

## Feedback Trigger (`scheduler` → `agents/feedback_agent.py`)

The scheduler owns feedback triggering. At the start of each session, before running
investigation, the scheduler queries the memory bank for positions due for evaluation.

**Trigger condition** (checked by `scheduler/scheduler.py` at each session start):
```python
# Positions whose evaluation window has arrived and are closed but not yet evaluated
positions_due = memory_bank.query(
    status IN ('CLOSED_STOP_LOSS', 'CLOSED_PROFIT_TARGET', 'CLOSED_WINDOW_EXPIRY'),
    evaluation_window_session == current_session_ordinal,
    # No FeedbackEvaluation record exists yet
)
```

The scheduler passes a `FeedbackInput` to `agents/feedback_agent.py` for each position due:

```python
@dataclass(frozen=True)
class FeedbackInput:
    position_id: int
    session_id: str             # session in which the position was opened
    ticker: str
    strategy: Literal["MEAN_REVERSION", "MOMENTUM"]
    html_report_path: str       # from Session.html_report_path of the entry session
    entry_price: float
    exit_price: float
    exit_reason: str
```

**Feedback agent responsibilities**:
1. Fetch the candle close price at evaluation time via the same `MarketDataClient` (`market_data/client.py`) the Investigation Agent uses, querying the specific past timestamp rather than the latest candle
2. Read HTML report at `html_report_path` to extract the original investment thesis
3. Compare thesis to outcome → produce `CORRECT`, `INCORRECT`, or `NEUTRAL` judgment
4. Write `FeedbackEvaluation` record to memory bank
5. Update `Position.status` to `EVALUATED`
6. Write `MemoryEntry` record for the ticker/strategy pair
7. Emit `AGENT_DECISION` telemetry event

**Retry policy** (spec FR-016a): up to 3 attempts per position. On 3rd failure:
- Write `FeedbackEvaluation` with `attempt_count=3` and partial data
- Update `Position.status` to `EVALUATION_FAILED`
- Emit `EVALUATION_FAILED` telemetry event (`position_id`, `ticker`, `error`)
- Unblock the ticker for new positions

**Ordering**: feedback evaluation runs before investigation in the same session. If
evaluation for multiple positions is due in the same session, they run sequentially.

---

## Monitor → Memory Bank (position close protocol)

The monitor communicates with the rest of the system exclusively through the memory bank.
There is no inter-thread signaling — the monitor writes, the scheduler reads.

**On exit condition detected** (`monitor/monitor.py`):
1. Call `alpaca-py` `close_position(ticker)` to close the position on Alpaca
2. On success: write `Position.exit_price`, `Position.exit_time`, `Position.exit_reason`,
   update `Position.status` to `CLOSED_STOP_LOSS` / `CLOSED_PROFIT_TARGET` / `CLOSED_WINDOW_EXPIRY`
3. Emit the appropriate trigger telemetry event (`STOP_LOSS_TRIGGERED`, `PROFIT_TARGET_TRIGGERED`,
   or `WINDOW_EXPIRY_TRIGGERED`, payload `ticker`/`exit_price`/`exit_reason`) followed by
   `POSITION_CLOSED` (payload `ticker`/`status`)
4. On `close_position` API failure: the bank is left unchanged and no telemetry is emitted;
   the position remains `OPEN` and is retried on the next poll cycle

**Monitor lifecycle**:
- Started as `threading.Thread` by `cli/main.py` at run startup, before the first session
- Stopped via `threading.Event` (stop signal) when the run ends normally or on hard abort
- If the run ends with positions still `OPEN`, the monitor thread is NOT stopped — it
  continues running until all open positions are closed (stop-loss, profit target, or
  window expiry). The CLI process must remain alive while positions are open.
- The stop signal is set only when no positions remain in `OPEN` status

---

## Memory Bank Startup Load

On `alphoryn run` startup, `memory/bank.py` loads all open positions:

```python
# All positions with status OPEN, regardless of run
open_positions = session.query(Position).filter(
    Position.status == "OPEN"
).order_by(Position.entry_time.asc()).all()
```

These are passed to the session loop and monitor at startup. Per FR-019: if a position
exists for a ticker from a prior run, that ticker is blocked from new Buy orders until the
position closes. The block is enforced in `execution/agent.py` at order time by checking
for an existing OPEN position for the same ticker before proceeding.
