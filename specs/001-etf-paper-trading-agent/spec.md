# Feature Specification: Alphoryn — Automated ETF Paper Trading System

**Feature Branch**: `001-etf-paper-trading-agent`

**Created**: 2026-07-03

**Status**: Draft

**Input**: User description: "Alphoryn V0.0.1 — an agentic system for automated ETF paper trading using LLM-assisted discretionary decision-making."

---

## Clarifications

### Session 2026-07-03

- Q: How are stop-loss and profit target thresholds defined? → A: Stop-loss is a hard config percentage (risk control, e.g., −2% from entry). Profit target is agent-determined per trade at entry: Mean Reversion targets the mean price level; Momentum uses a trailing stop. Neither is a fixed config value for profit.
- Q: When both ETFs trigger Buy in the same session, how is the session money budget allocated? → A: ETF orders execute sequentially; each order is validated against the full remaining budget at the time of execution (first-come-first-served). No pre-split or conviction-based allocation.
- Q: What happens if the memory bank is inaccessible or corrupted at run startup? → A: Abort with a clear error message; the run must not start. The user must resolve the memory bank before proceeding.
- Q: How are sessions uniquely identified? → A: Sequential run number combined with a random short sequence for the session within that run (e.g., `run-1/session-a3f7`). Run number increments across runs; session ID is randomly generated per session.
- Q: What does the user see during the 52-minute investigation window? → A: Periodic heartbeat lines at a fixed interval (e.g., "investigating… 12 min elapsed") — enough to confirm the system is alive without cluttering the output.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Configure and Launch a Trading Session (Priority: P1)

A user provides configuration (two ETFs, candle timeframe, run duration, exchange, and an optional session money budget) and starts the system. The system validates the configuration, calculates the total number of sessions, warns if the session count is fractional, and waits in an idle countdown until the next candle boundary before beginning.

**Why this priority**: This is the entry point for the entire system. Nothing can function without a valid, started session.

**Independent Test**: Can be fully tested by supplying a valid configuration and confirming the system reaches the "waiting for candle close" idle state with correct session count displayed, without executing any trades.

**Acceptance Scenarios**:

1. **Given** a valid config with a 24H run duration and 1H candle timeframe, **When** the user starts the system, **Then** the system displays "6 sessions planned" and begins counting down to the next candle boundary.
2. **Given** a run duration that does not divide cleanly into the candle timeframe, **When** the user starts the system, **Then** the system warns about fractional sessions, rounds down, and suggests a config adjustment.
3. **Given** an invalid or missing configuration field, **When** the user starts the system, **Then** the system surfaces a clear error and does not proceed.

---

### User Story 2 — Autonomous Per-Session Decision Cycle (Priority: P1)

At each candle close, the system wakes, checks whether the run is still active and the market is open, investigates market data for both ETFs, performs independent regime recognition per ETF, selects a strategy per ETF (each ETF may end up on a different strategy in the same session), decides Buy/Sell/Hold per ETF, executes the decisions via the paper trading interface, and produces a session HTML report. This cycle repeats until the run completes.

**Why this priority**: This is the core value of the system — autonomous decision-making over a configured run period.

**Independent Test**: Can be tested by running a single-session scenario: the system receives one candle close, completes the full investigate-decide-execute cycle, generates an HTML report, and writes a memory bank entry — without a second candle close being required.

**Acceptance Scenarios**:

1. **Given** a candle has closed and the market is open, **When** the session begins, **Then** the system takes a frozen data snapshot, investigates within the budget window, produces a Buy/Sell/Hold decision per ETF, and executes it.
2. **Given** investigation does not complete within the 52-minute budget, **When** the budget expires, **Then** the system forces a Hold on all ETFs for that session and logs a timeout warning.
3. **Given** the session money budget is set and an order would exceed the remaining budget, **When** execution is attempted, **Then** the order is skipped, the skip is logged, and the position is held.
4. **Given** the market is closed at the time of a candle close, **When** the session check runs, **Then** the system logs the closure, displays a countdown to market open, and waits without consuming session budget.

---

### User Story 3 — Position Lifecycle and Risk Management (Priority: P2)

After a trade is placed, the system monitors the open position continuously and exits it automatically when a profit target, stop-loss, or evaluation window expiry is reached — without LLM involvement. The system also prevents the main decision agent from opening a new position on an ETF until the feedback agent has evaluated and closed the prior trade on that ETF.

**Why this priority**: Unclosed positions and unguarded risk are the primary financial failure modes. This must be in place before any live trading sessions run.

**Independent Test**: Can be tested by opening a simulated position and verifying that a price reaching the stop-loss threshold triggers an automatic exit, while the main agent is correctly blocked from opening a new position on the same ETF.

**Acceptance Scenarios**:

1. **Given** an open position where the price hits the configured stop-loss, **When** the monitoring loop detects this, **Then** the position is closed automatically and logged without any LLM call.
2. **Given** an open position on ETF-1 whose feedback has not been evaluated, **When** the main agent considers ETF-1, **Then** it is forced to Hold on ETF-1 regardless of investigation output.
3. **Given** an open position on ETF-1 and no open position on ETF-2, **When** a session runs, **Then** the main agent can freely decide on ETF-2 while being forced to Hold on ETF-1.
4. **Given** a position whose evaluation window has expired without hitting profit target or stop-loss, **When** the expiry is detected, **Then** the position is closed and the fact is logged.

---

### User Story 4 — Feedback Evaluation and Memory Learning (Priority: P2)

At a strategy-defined point after the entry session (1–2 sessions for Momentum, 3–6 for Mean Reversion), a feedback agent evaluates whether the original trading thesis was correct by comparing what was decided against what actually happened. The evaluation result is written to the memory bank, closing the learning loop for that trade.

**Why this priority**: Without feedback evaluation, the system cannot improve regime recognition over time and cannot unblock the main agent from trading the affected ETF.

**Independent Test**: Can be tested by simulating a completed trade entry and fast-forwarding to the evaluation window, then confirming the feedback agent produces a structured judgment record in the memory bank and marks the trade as evaluated.

**Acceptance Scenarios**:

1. **Given** a Momentum trade entry session, **When** 1–2 candle sessions have elapsed, **Then** the feedback agent reads the entry HTML report, fetches the candle close price at evaluation time, and writes a judgment to the memory bank.
2. **Given** the feedback agent has written its evaluation, **When** the main agent next considers that ETF, **Then** it is free to open a new position on that ETF.
3. **Given** the feedback agent encounters an error at evaluation time, **When** the attempt fails, **Then** the feedback agent retries immediately up to 3 times. If all 3 attempts fail, the evaluation is marked failed, the ETF is unblocked, and a warning is logged — the position is considered closed from the main agent's perspective.

---

### Edge Cases

- What happens if both ETFs have open, feedback-unevaluated positions simultaneously? (System should Hold on both ETFs until at least one feedback evaluation completes.)
- What happens if the real-time price feed becomes unavailable mid-session while a stop-loss is active? (System suspends trading, alerts the user, and resumes when feed is restored.)
- What happens if a candle close occurs while the system is still in the execution phase of the previous session? (The new session is skipped and does not count against the run total.)
- What happens if the paper trading API is unavailable at execution time? (System logs the intended action, holds the position, and retries at the next session.)
- What happens if the run completes while a position is still open? (Position remains open under continuous stop-loss monitoring; run completion does not force-close positions.)
- What happens if a new run starts and carry-over positions from a previous run exist in the memory bank? (System loads them, applies position-blocking immediately for any with unevaluated feedback, and resumes stop-loss monitoring at market open — the new run is never a clean slate.)
- What happens if the memory bank is inaccessible or corrupted at run startup? (System aborts with a clear error message; the run must not start in a degraded state. User must restore the memory bank before retrying.)

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a configuration specifying two ETFs, candle timeframe, run duration, target exchange, an optional per-session money budget, a maximum startup latency window (`max_startup_latency_seconds`), and a stop-loss percentage applied as a hard risk control at trade entry.
- **FR-002**: System MUST calculate total session count as `run_duration / candle_timeframe` (rounded down) at startup and display it to the user.
- **FR-003**: System MUST warn the user if the session count is fractional and suggest a configuration adjustment.
- **FR-004**: System MUST align to the next candle boundary (not system start time) before triggering the first session, and display the wait time.
- **FR-005**: System MUST check, at each session start, whether the run is complete, the market is open, and whether any ETF has a feedback-blocked position. At the start of a new run, the system MUST additionally load all open positions from the memory bank and immediately apply position-blocking rules for any unevaluated carry-over positions.
- **FR-006**: System MUST take a frozen market data snapshot at each candle close and reason exclusively over that snapshot during investigation; no live data may be fetched during investigation.
- **FR-007**: System MUST enforce a 52-minute investigation budget and a 7-minute decide+execute budget per session; overruns MUST force a Hold decision and emit a warning log. During investigation, the system MUST emit periodic heartbeat lines at a user-visible fixed interval indicating elapsed time (e.g., "investigating… 12 min elapsed"), so the user can confirm the system is active without interpreting silence as a hang.
- **FR-008**: System MUST perform regime recognition independently for each ETF within a session and select a strategy (Mean Reversion or Momentum) per ETF. One ETF may be assigned Mean Reversion while the other is assigned Momentum in the same session. The investigation step covers both ETFs but produces independent strategy selection and decision outputs for each.
- **FR-009**: System MUST produce one of three actions per ETF per session: Buy, Sell, or Hold.
- **FR-010**: System MUST enforce the session money budget at execution time: each ETF order is checked against the full remaining budget at the moment of execution, in sequence. If an order would exceed the remaining budget, that order is skipped and logged; the other ETF's order is unaffected. No pre-session budget split between ETFs is performed.
- **FR-011**: System MUST generate a structured HTML report after each session, stored under the session's composite ID (`run-N/session-<random>`), recording per-ETF strategy, decision, reasoning, execution result, and any warnings.
- **FR-012**: System MUST write a memory bank entry after each session recording strategy selected, regime context, and decision.
- **FR-013**: System MUST continuously monitor open positions using real-time price data and trigger deterministic exits (no LLM involvement) on three conditions: (1) price breaches the configured stop-loss percentage from entry price; (2) price reaches the agent-set exit target recorded at trade entry (mean-reversion price level or trailing stop for Momentum); (3) evaluation window expires without either prior exit triggering.
- **FR-014**: System MUST block the main agent from opening a new position on an ETF while that ETF has an open, feedback-unevaluated position. Each ETF is independent.
- **FR-015**: System MUST trigger the feedback agent at the strategy-defined evaluation window (1–2 sessions post-entry for Momentum; 3–6 sessions for Mean Reversion).
- **FR-016**: Feedback agent MUST write a structured evaluation (thesis vs. outcome judgment) to the memory bank and mark the position as evaluated.
- **FR-016a**: If a feedback evaluation attempt fails, the feedback agent MUST retry immediately up to 3 times. After 3 consecutive failures, the evaluation MUST be marked as failed, the ETF MUST be unblocked for new trades, and a warning MUST be logged. The position is treated as closed from the main agent's perspective.
- **FR-017**: System MUST handle all failure conditions (API unavailable, market closed, budget exceeded, skill unavailable) with a Hold action and a structured log entry; no failure condition may leave a position in an ambiguous state.
- **FR-018**: Timed-out sessions and data-unavailability skips MUST NOT count against the derived session total.
- **FR-019**: When a new run starts, the system MUST load all open positions from the memory bank, apply position-blocking rules for any with unevaluated feedback, and resume stop-loss monitoring for all carry-over positions at market open. Every run begins position-aware; no run starts as a clean slate. If the memory bank is inaccessible or corrupted at startup, the system MUST abort with a clear error message — the run must not proceed in a degraded state.

### Key Entities

- **Configuration**: ETF pair, candle timeframe, run duration, exchange, optional money budget. The single source of truth for all session parameters.
- **Session**: One atomic decision unit triggered by a candle close. Identified by a composite key of sequential run number and a randomly generated short sequence (e.g., `run-1/session-a3f7`). Contains a snapshot and per-ETF investigation outputs — each ETF produces an independent strategy selection, decision, and execution result. The session HTML report captures both ETFs' outputs and is stored under the session's composite ID.
- **Position**: An open paper trade on one ETF. Tracks entry price, strategy, status (open/closed/evaluated), a hard stop-loss level (derived from the configured stop-loss percentage applied at entry), and a strategy-determined exit target (price level for Mean Reversion; trailing stop for Momentum — both set by the agent at trade entry).
- **Memory Bank**: A per-ETF structured store accumulating strategy performance, regime context summaries, and feedback evaluations across all sessions.
- **HTML Report**: A fixed-template session record generated after each session. Consumed by the feedback agent at evaluation time.
- **Feedback Evaluation**: A structured record written by the feedback agent after comparing the entry thesis to the actual price outcome.

---

## Success Criteria *(mandatory)*

- **SC-001**: A user can start a configured trading session and reach the "waiting for candle close" idle state within 2 minutes of invoking the system.
- **SC-002**: The system aligns to the next candle boundary within the configured `max_startup_latency_seconds` window. If alignment is delayed beyond this threshold, the system logs a warning and proceeds — it never blocks or silently skips a session due to startup latency alone.
- **SC-003**: Every session produces either a completed decision record (Buy/Sell/Hold with HTML report) or a logged skip entry with reason — no session ends silently.
- **SC-004**: Every failure condition results in a log entry with sufficient detail for the user to identify the cause without additional instrumentation.
- **SC-005**: Stop-loss exits trigger within one 1-minute candle of the threshold being breached.
- **SC-006**: Feedback evaluations are triggered within one session of the strategy-defined evaluation window.
- **SC-007**: The memory bank accurately reflects cumulative strategy performance and all feedback evaluations across the full run.
- **SC-008**: The system accepts any two ETFs supplied by the user at configuration time; no specific pre-defined ETFs are required. The ETF pair is treated as a generic config value and the system applies the same strategy rules regardless of which ETFs are chosen.

---

## Assumptions

- Paper trading is the only mode in scope for V0.0.1; live trading is explicitly out of scope.
- The system runs as a single-process, single-machine application; distributed or cloud-hosted execution is out of scope.
- Market data and real-time price feeds are sourced from a single, user-configured external API per exchange.
- The memory bank and HTML reports are stored locally on the host machine.
- "Session money budget" applies per session, not as a cumulative portfolio limit across the full run.
- The two ETFs operate independently throughout the system; no cross-ETF correlation logic is required in V0.0.1.
- Mean Reversion and Momentum are the only two strategies. Each ETF undergoes independent regime recognition per session and receives its own strategy assignment; the two ETFs may run different strategies in the same session.
- The agent determines lot size as part of its Buy decision, constrained by the session money budget communicated to it before investigation begins. The execution workflow validates the order value against the remaining budget at execution time and skips if exceeded.
- The feedback agent evaluates a trade only once; re-evaluation is out of scope.
- Run completion does not force-close open positions; positions remain under stop-loss monitoring after the run ends and are persisted in the memory bank so they are carried into subsequent runs.
