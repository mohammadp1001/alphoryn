# Feature Specification: Alphoryn — Automated Ticker Paper Trading System

**Feature Branch**: `001-etf-paper-trading-agent`

**Created**: 2026-07-03

**Status**: Implemented

**Input**: User description: "Alphoryn V0.0.1 — an agentic system for automated ETF paper trading using LLM-assisted discretionary decision-making."

---

## Clarifications

### Session 2026-07-03

- Q: How are stop-loss and profit target thresholds defined? → A: Stop-loss is a hard config percentage (risk control, e.g., −2% from entry). Profit target is agent-determined per trade at entry: Mean Reversion targets the mean price level; Momentum uses a trailing stop. Neither is a fixed config value for profit.
- Q: When multiple tickers trigger Buy in the same session, how is the session money budget allocated? → A: Ticker orders execute sequentially; each order is validated against the full remaining budget at the time of execution (first-come-first-served). No pre-split or conviction-based allocation.
- Q: What happens if the memory bank is inaccessible or corrupted at run startup? → A: Abort with a clear error message; the run must not start. The user must resolve the memory bank before proceeding.
- Q: How are sessions uniquely identified? → A: Sequential run number combined with a zero-padded sequential session number within that run (e.g., `run-3/session-0001`). Run number increments across runs; session number increments within each run.
- Q: What does the user see during the investigation window? → A: Periodic heartbeat lines at a fixed interval (e.g., "investigating… 12 min elapsed") — enough to confirm the system is alive without cluttering the output.

### Session 2026-07-07

- Q: How many tickers does the system support? → A: Minimum two tickers required; the system supports any number of US-listed tickers configured in `tickers: list[str]`. The original two-ETF constraint is generalised — tickers are evaluated independently in every session.
- Q: How are market hours and exchange determined? → A: Market hours are sourced from Alpaca's market calendar API. No exchange configuration is required; the system is scoped to US equities (NYSE, NASDAQ, AMEX) only.
- Q: What configuration parameters have been added since the original spec? → A: `extended_hours: bool` (allow pre/post-market execution; testing affordance), `memory_db_path: str` (path to local SQLite memory bank, default `~/.alphoryn/memory.db`). `exchange` has been removed.
- Q: How are the four agents architecturally separated? → A: Two are LLM-assisted (Investigation Agent, Feedback Agent); two are fully deterministic (Execution Agent, Position Monitor). Deterministic agents contain no LLM calls — this is verified by tests asserting zero model calls. Agents communicate via structured typed records, not natural language. The HTML report is the only cross-agent artifact.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Configure and Launch a Trading Session (Priority: P1)

A user provides configuration (a list of tickers, candle timeframe, run duration, an optional session money budget, and an optional extended-hours flag) and starts the system. The system validates the configuration, calculates the total number of sessions, warns if the session count is fractional, and waits in an idle countdown until the next candle boundary before beginning.

**Why this priority**: This is the entry point for the entire system. Nothing can function without a valid, started session.

**Independent Test**: Can be fully tested by supplying a valid configuration and confirming the system reaches the "waiting for candle close" idle state with correct session count displayed, without executing any trades.

**Acceptance Scenarios**:

1. **Given** a valid config with a 24H run duration and 1H candle timeframe, **When** the user starts the system, **Then** the system displays "24 sessions planned" and begins counting down to the next candle boundary.
2. **Given** a run duration that does not divide cleanly into the candle timeframe, **When** the user starts the system, **Then** the system warns about fractional sessions, rounds down, and suggests a config adjustment.
3. **Given** an invalid or missing configuration field, **When** the user starts the system, **Then** the system surfaces a clear error and does not proceed.

---

### User Story 2 — Autonomous Per-Session Decision Cycle (Priority: P1)

At each candle close, the system wakes, checks whether the run is still active and the market is open, investigates market data for all configured tickers, performs independent regime recognition per ticker, selects a strategy per ticker (each ticker may end up on a different strategy in the same session), decides Buy/Sell/Hold per ticker, executes the decisions via the paper trading interface, and produces a unified session HTML report covering all tickers. This cycle repeats until the run completes.

**Why this priority**: This is the core value of the system — autonomous decision-making over a configured run period.

**Independent Test**: Can be tested by running a single-session scenario: the system receives one candle close, completes the full investigate-decide-execute cycle, generates a unified HTML report, and writes a memory bank entry — without a second candle close being required.

**Acceptance Scenarios**:

1. **Given** a candle has closed and the market is open, **When** the session begins, **Then** the system takes a frozen data snapshot for all tickers, investigates within the budget window, produces a Buy/Sell/Hold decision per ticker, and executes it.
2. **Given** investigation does not complete within the session investigation budget, **When** the budget expires, **Then** the system forces a Hold on all tickers for that session and logs a timeout warning.
3. **Given** the session money budget is set and an order would exceed the remaining budget, **When** execution is attempted, **Then** the order is skipped, the skip is logged, and the position is held.
4. **Given** the market is closed at the time of a candle close, **When** the session check runs, **Then** the system logs the closure, displays a countdown to market open, and waits without consuming session budget.

---

### User Story 3 — Position Lifecycle and Risk Management (Priority: P2)

After a trade is placed, the system monitors the open position continuously and exits it automatically when a profit target, stop-loss, or evaluation window expiry is reached — without LLM involvement. The system also prevents the main decision agent from opening a new position on a ticker until the feedback agent has evaluated and closed the prior trade on that ticker.

**Why this priority**: Unclosed positions and unguarded risk are the primary financial failure modes. This must be in place before any live trading sessions run.

**Independent Test**: Can be tested by opening a simulated position and verifying that a price reaching the stop-loss threshold triggers an automatic exit, while the main agent is correctly blocked from opening a new position on the same ticker.

**Acceptance Scenarios**:

1. **Given** an open position where the price hits the configured stop-loss, **When** the monitoring loop detects this, **Then** the position is closed automatically and logged without any LLM call.
2. **Given** an open position on ticker-A whose feedback has not been evaluated, **When** a session begins, **Then** ticker-A is excluded from the investigation step entirely (no LLM investigation call is made for it) and its session outcome is recorded as Hold.
3. **Given** an open position on ticker-A and no open position on ticker-B, **When** a session runs, **Then** the main agent can freely decide on ticker-B while being forced to Hold on ticker-A.
4. **Given** a position whose evaluation window has expired without hitting profit target or stop-loss, **When** the expiry is detected, **Then** the position is closed and the fact is logged. *** Added by me, Let's clarify wht evaluation window is? ***

---

### User Story 4 — Feedback Evaluation and Memory Learning (Priority: P2)

At a strategy-defined point after the entry session (1–2 sessions for Momentum, 3–6 for Mean Reversion), a feedback agent evaluates whether the original trading thesis was correct by comparing what was decided against what actually happened. The evaluation result is written to the memory bank, closing the learning loop for that trade.

**Why this priority**: Without feedback evaluation, the system cannot improve regime recognition over time and cannot unblock the main agent from trading the affected ticker.

**Independent Test**: Can be tested by simulating a completed trade entry and fast-forwarding to the evaluation window, then confirming the feedback agent produces a structured judgment record in the memory bank and marks the trade as evaluated.

**Acceptance Scenarios**:

1. **Given** a Momentum trade entry session, **When** 1–2 candle sessions have elapsed, **Then** the feedback agent reads the entry HTML report, calls the same market data tool the Investigation Agent uses to fetch the candle close price at evaluation time, and writes a judgment to the memory bank.
2. **Given** the feedback agent has written its evaluation, **When** the main agent next considers that ticker, **Then** it is free to Buy, Sell, or Hold on that ticker, and its investigation input includes the ticker's recent feedback judgments from the memory bank so the decision can account for whether the prior thesis was correct.
3. **Given** the feedback agent encounters an error at evaluation time, **When** the attempt fails, **Then** the feedback agent retries immediately up to 3 times. If all 3 attempts fail, the evaluation is marked failed, the ticker is unblocked, and a warning is logged — the position is considered closed from the main agent's perspective.

---

### Edge Cases

- What happens if multiple tickers all have open, feedback-unevaluated positions simultaneously? (System should Hold on all affected tickers until at least one feedback evaluation completes; unaffected tickers remain free.)
- What happens if the real-time price feed becomes unavailable mid-session while a stop-loss is active? (System suspends trading, alerts the user, and resumes when feed is restored.)
- What happens if a candle close occurs while the system is still in the execution phase of the previous session? (The new session is skipped and does not count against the run total.)
- What happens if the paper trading API is unavailable at execution time? (System logs the intended action, holds the position, and retries at the next session.)
- What happens if the run completes while a position is still open? (Position remains open under continuous stop-loss monitoring; run completion does not force-close positions.)
- What happens if a new run starts and carry-over positions from a previous run exist in the memory bank? (System loads them, applies position-blocking immediately for any with unevaluated feedback, and resumes stop-loss monitoring at market open — the new run is never a clean slate.)
- What happens if the memory bank is inaccessible or corrupted at run startup? (System aborts with a clear error message; the run must not start in a degraded state. User must restore the memory bank before retrying.)

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a configuration specifying a list of tickers (minimum two, US-listed), candle timeframe, run duration, an optional per-session money budget, a stop-loss percentage applied as a hard risk control at trade entry, an extended-hours flag (`extended_hours`), and a memory bank path (`memory_db_path`). No exchange configuration is required; market hours are sourced from the trading platform's market calendar.
- **FR-002**: System MUST calculate total session count as `run_duration / candle_timeframe` (rounded down) at startup and display it to the user.
- **FR-003**: System MUST warn the user if the session count is fractional and suggest a configuration adjustment.
- **FR-004**: System MUST align to the next candle boundary (not system start time) before triggering the first session, and display the wait time.
- **FR-005**: System MUST check, at each session start, whether the run is complete, the market is open, and whether any ticker has a feedback-blocked position (a closed position with no `FeedbackEvaluation` yet, per FR-014). Feedback-blocked tickers MUST be excluded from the investigation step entirely for that session — no Investigation Agent call is made for them — and their session outcome is recorded as Hold. At the start of a new run, the system MUST additionally load all open positions from the memory bank and immediately apply position-blocking rules for any unevaluated carry-over positions (positions still `OPEN`, or closed but unevaluated, at the time a new run starts, per FR-019).
- **FR-006**: System MUST take a frozen market data snapshot at each candle close and reason exclusively over that snapshot during investigation; no live data may be fetched during investigation.
- **FR-007**: System MUST enforce a session investigation budget of ≤87% of the candle timeframe and a decide+execute budget of ≤13% of the candle timeframe (for a 1H candle: 52 min / 7 min). Overruns MUST force a Hold decision on all tickers and emit a warning log. During investigation, the system MUST emit periodic heartbeat lines at a fixed interval indicating elapsed time (e.g., "investigating… 12 min elapsed"), so the user can confirm the system is active.
- **FR-008**: System MUST perform regime recognition independently for each ticker within a session and select a strategy (Mean Reversion or Momentum) per ticker. One ticker may be assigned Mean Reversion while another is assigned Momentum in the same session. The investigation step covers all tickers but produces independent strategy selection and decision outputs for each.
- **FR-008a**: Before investigating a ticker, the system MUST supply the Investigation Agent with that ticker's recent feedback judgments and strategy performance history from the memory bank, so the decision (including whether to continue, reverse, or exit an unblocked position) can account for prior evaluation outcomes.
- **FR-009**: System MUST produce one of three actions per ticker per session: Buy, Sell, or Hold.
- **FR-010**: System MUST enforce the session money budget at execution time: each ticker order is checked against the full remaining budget at the moment of execution, in sequence. If an order would exceed the remaining budget, that order is skipped and logged; other tickers' orders are unaffected. No pre-session budget split between tickers is performed. This execution-time check is a hard, deterministic backstop regardless of what the Investigation Agent reasoned about.
- **FR-010a**: The Investigation Agent MUST be given the session money budget as part of its input, and when it produces Buy decisions with lot sizes for more than one ticker in the same session, it MUST reason about them jointly against that shared budget (e.g., not size every ticker's order as if it alone had the full budget), since execution consumes the budget sequentially, ticker by ticker. This is advisory sizing guidance only — FR-010's execution-time check remains authoritative and may still skip an order the agent sized optimistically.
- **FR-011**: System MUST generate a unified HTML report after each session covering all tickers, recording per-ticker strategy, action, reasoning, execution result, and any warnings. The report is stored under a composite session identifier (e.g., `run-3/session-0001`).
- **FR-012**: System MUST write a memory bank entry after each session recording strategy selected, regime context, and decision per ticker.
- **FR-013**: System MUST continuously monitor open positions using real-time price data and trigger deterministic exits (no LLM involvement) on three conditions: (1) price breaches the configured stop-loss percentage from entry price; (2) price reaches the agent-set exit target recorded at trade entry (mean-reversion price level or trailing stop for Momentum); (3) evaluation window expires without either prior exit triggering.
- **FR-014**: System MUST block the main agent from opening a new position on a ticker while that ticker has an open, feedback-unevaluated position. Each ticker is independent.
- **FR-015**: System MUST trigger the feedback agent at the strategy-defined evaluation window (1–2 sessions post-entry for Momentum; 3–6 sessions for Mean Reversion).
- **FR-016**: Feedback agent MUST write a structured evaluation (thesis vs. outcome judgment) to the memory bank and mark the position as evaluated. It MUST use the same market data tool as the Investigation Agent to fetch the price at the evaluation timestamp, querying that specific past candle close rather than the latest one.
- **FR-016a**: If a feedback evaluation attempt fails, the feedback agent MUST retry immediately up to 3 times. After 3 consecutive failures, the evaluation MUST be marked as failed, the ticker MUST be unblocked for new trades, and a warning MUST be logged. The position is treated as closed from the main agent's perspective.
- **FR-017**: System MUST handle all failure conditions (API unavailable, market closed, budget exceeded, skill unavailable) with a Hold action and a structured log entry; no failure condition may leave a position in an ambiguous state.
- **FR-018**: Timed-out sessions and data-unavailability skips MUST NOT count against the derived session total.
- **FR-019**: When a new run starts, the system MUST load all open positions from the memory bank, apply position-blocking rules for any with unevaluated feedback, and resume stop-loss monitoring for all carry-over positions at market open. Every run begins position-aware; no run starts as a clean slate. If the memory bank is inaccessible or corrupted at startup, the system MUST abort with a clear error message — the run must not proceed in a degraded state.

### Agent Architecture

The system is composed of four agents with a strict separation between reasoning (LLM-assisted) and execution (deterministic). This separation is a non-negotiable design principle: any agent that places or closes a trade MUST be deterministic and produce identical outputs for identical inputs.

**Investigation Agent** (LLM-assisted, reasoning)
Responsible for market regime recognition and per-session decision-making. At each candle close it receives a frozen market data snapshot, plus each ticker's recent feedback judgments and strategy performance history from the memory bank, and produces a structured decision record — one action (Buy/Sell/Hold), strategy, lot size, exit target, and reasoning summary per ticker. Aside from the memory bank query, it operates exclusively on the frozen snapshot; no live market data may be queried during the decision process. Feedback-blocked tickers (FR-005) are excluded from its input entirely — it is never invoked for a blocked ticker, and that ticker's session outcome is recorded as Hold without an investigation call. Invoked once per candle close, per unblocked ticker.

**Execution Agent** (deterministic, no reasoning)
Responsible for carrying out the decisions produced by the investigation agent. Processes each ticker's decision sequentially, validates it against the session money budget, and submits market orders. Contains no LLM logic; given the same inputs it always produces the same result. Execution failures result in a Hold and a log entry, never in a retry loop.

**Position Monitor** (deterministic, continuous)
Runs concurrently with the session loop as a background process. Continuously polls real-time price data and closes positions when any of three exit conditions is met: stop-loss breach, profit-target reached, or evaluation window expired. Makes no LLM calls. Thread-safe with respect to the session loop.

**Feedback Agent** (LLM-assisted, reasoning)
Triggered once per closed position at the strategy-defined evaluation window. Reads the original session HTML report to extract the entry reasoning, then calls the same market data tool the Investigation Agent uses (`market_data/client.py`) to fetch the actual price outcome at the evaluation timestamp, and writes a structured judgment (Correct / Incorrect / Neutral) to the memory bank. Unlike the Investigation Agent's snapshot-isolated call, the Feedback Agent's tool call targets a specific past candle close rather than the latest one. Unblocks the ticker for future trades after evaluation (or after exhausting its retry policy). Invoked by the session loop before investigation begins.

**Interaction flow:**

```
[candle close]
    Investigation Agent  →  structured decision per ticker
    Execution Agent      →  market orders + open Position records
    Position Monitor     →  continuous price polling → close Position on exit trigger
[evaluation window]
    Feedback Agent       →  reads HTML report → writes FeedbackEvaluation → unblocks ticker
```

Each agent communicates via structured records written to the memory bank or passed as typed data — no agent reads or interprets another agent's natural language output directly. The HTML report is the only cross-agent artifact, and only the feedback agent reads it.

### Key Entities

- **Configuration**: List of tickers (min 2, US-listed), candle timeframe, run duration, optional money budget, extended-hours flag, stop-loss percentage, memory bank path. The single source of truth for all session parameters.
- **Session**: One atomic decision unit triggered by a candle close. Identified by a composite key of sequential run number and a zero-padded sequential session number (e.g., `run-3/session-0001`). Contains a frozen data snapshot and per-ticker investigation outputs — each ticker produces an independent strategy selection, action, and execution result. The unified session HTML report captures all tickers and is stored under the session's composite ID.
- **Position**: An open paper trade on one ticker. Tracks entry price, strategy, status (open/closed/evaluated), a hard stop-loss level (derived from the configured stop-loss percentage applied at entry), and a strategy-determined exit target (price level for Mean Reversion; trailing stop for Momentum — both set by the investigation agent at trade entry).
- **Memory Bank**: A structured local store accumulating per-ticker strategy performance, regime context summaries, and feedback evaluations across all sessions and runs. Persists across runs.
- **HTML Report**: A unified session record generated after each session covering all configured tickers. The primary artifact shared between the session loop and the feedback agent.
- **Feedback Evaluation**: A structured record written by the feedback agent after comparing the entry thesis to the actual price outcome for a single ticker position.

---

## Success Criteria *(mandatory)*

- **SC-001**: A user can start a configured trading session and reach the "waiting for candle close" idle state within 2 minutes of invoking the system.
- **SC-002**: The system aligns to the next candle boundary at startup. If alignment is delayed, the system logs a warning and proceeds — it never blocks or silently skips a session due to startup latency alone.
- **SC-003**: Every session produces either a completed decision record (Buy/Sell/Hold with unified HTML report) or a logged skip entry with reason — no session ends silently.
- **SC-004**: Every failure condition results in a log entry with sufficient detail for the user to identify the cause without additional instrumentation.
- **SC-005**: Stop-loss exits trigger within one 1-minute candle of the threshold being breached.
- **SC-006**: Feedback evaluations are triggered within one session of the strategy-defined evaluation window.
- **SC-007**: The memory bank accurately reflects cumulative per-ticker strategy performance and all feedback evaluations across the full run.
- **SC-008**: The system accepts any list of two or more US-listed tickers supplied by the user at configuration time; no specific pre-defined tickers are required. All tickers are evaluated using the same strategy rules regardless of which symbols are chosen.

---

## Assumptions

- Paper trading is the only mode in scope for V0.0.1; live trading is explicitly out of scope.
- The system runs as a single-process, single-machine application; distributed or cloud-hosted execution is out of scope.
- Market data, real-time price feeds, and market calendar are sourced from Alpaca's paper trading platform. US equities (NYSE, NASDAQ, AMEX) are the only supported market.
- The memory bank and HTML reports are stored locally on the host machine.
- "Session money budget" applies per session, not as a cumulative portfolio limit across the full run.
- All configured tickers operate independently throughout the system; no cross-ticker correlation logic is required in V0.0.1.
- Mean Reversion and Momentum are the only two strategies. Each ticker undergoes independent regime recognition per session and receives its own strategy assignment; multiple tickers may run different strategies in the same session.
- The agent determines lot size as part of its Buy decision, constrained by the session money budget communicated to it before investigation begins, and reasons jointly across all tickers it decides to Buy in the same session so it doesn't size each order as if it alone had the full budget (FR-010a). The execution workflow validates each order's value against the remaining budget at execution time, in sequence, and skips if exceeded (FR-010) — this hard check is authoritative regardless of the agent's sizing.
- The feedback agent evaluates a trade only once; re-evaluation is out of scope.
- Run completion does not force-close open positions; positions remain under stop-loss monitoring after the run ends and are persisted in the memory bank so they are carried into subsequent runs.
- `extended_hours: true` is a testing affordance; production runs should use standard market hours.
