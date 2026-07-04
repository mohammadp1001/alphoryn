# alphoryn V_0.0.1

## Overview

An agentic system for automated ETF paper trading using LLM-assisted discretionary decision-making. The system reasons over available resources within a time-and-money-budgeted session and executes decisions via a deterministic execution agent.

---

## Configuration

| Parameter | Value |
|---|---|
| Mode | Paper trading only |
| ETFs | Two specific ETFs (TBD) |
| Candle timeframe | User-defined (default: 1H) |
| Run duration | User-defined in clock time (default: 24H) |
| Market hours | User-defined (exchange-dependent) |
| Exchange | User-defined (e.g. XETRA, Euronext, LSE) |
| Actions | Buy / Sell / Hold |
| Strategies | Mean Reversion, Momentum (agent-selected per ETF per session) |
| Stop-loss threshold | User-defined in config (EUR or %) |
| Max startup latency | User-defined in config (seconds) |
| Currency | EUR (default) |
| Session money budget | User-defined (default: none) |

---

## Core Concepts

### Candle Timeframe
The resolution of market data the strategy reads. Set to **1H** — meaning each candle covers one hour of price action (Open / High / Low / Close).

### Candle Close
The moment a candle's time period ends and its final price is locked. This event **triggers each session**. Candles close on fixed boundaries determined by the configured exchange and candle timeframe.

### Session
A single atomic decision unit — one candle close, one investigation, one action. The system always aligns to market candle boundaries, not to the system start time.

> If the system starts at 11:47 ET, it waits until 12:00 ET for the first candle close. This wait is displayed explicitly to the user.

### Run Duration
User-defined in clock time (default: 24H). The system derives the session count automatically at startup:

> `sessions = run duration / candle timeframe` (rounded down)

| Run duration | Candle timeframe | Sessions |
|---|---|---|
| 24H | 1H | 6 |
| 24H | 4H | 1 |
| 24H | 30min | 12 |

**Fractional session warning:** If the division does not produce a whole number, the system warns the user at startup and rounds down. The user should adjust run duration or candle timeframe to produce a clean result.

---

## Session Workflow

```
wait for candle close
    → check run duration
    → check market hours
    → check open positions
    → investigate
    → decide
    → execute
    → update memory
[next candle close(s) — strategy-dependent]
    → feedback agent
```

### Time Budget per Session

Every session must complete within **60 minutes** (one candle timeframe).

| Step | Budget |
|---|---|
| Check run duration + market hours + open positions | ~1 min |
| Investigate | ~52 min |
| Decide + Execute | ~7 min |

**Memory update and feedback run outside the session budget.**

**Feedback runs after the session closes** and is not part of the session budget.

---

## Step Definitions

### 1. Wait for Candle Close
System is idle until the hourly candle closes. Example: at 10:00 ET, the 09:00–10:00 candle closes with locked OHLC data. This wakes the system.

### 2. Check Run Duration
Verify the run has not completed. Session count is derived at startup from run duration / candle timeframe (rounded down).

- Current session < derived session count → proceed
- Current session = derived session count → log completion message, exit, return control to user

**Timed-out sessions** are skipped and do not count toward the derived session total.

### 3. Check Market Hours
Verify the market is open and sufficient time remains in the session budget.

- Market open → proceed
- Market closed → log message with timer showing time until next open, wait

### 4. Check Open Positions
Per ETF, verify whether a position is currently open and awaiting feedback evaluation.

- No open position → main agent free to investigate and decide Buy / Sell / Hold
- Open position, feedback not yet evaluated → main agent forced to Hold on that ETF
- Open position, feedback evaluated and closed → main agent free again

The two ETFs are independent. An open position on ETF-1 does not block trading on ETF-2.

### 5. Investigate
The agent takes a **frozen snapshot** of all required data at session start and reasons over it. No live data is consumed during investigation — the snapshot is static.

**Resources (always available):**
- Skills (authored md files — analytical methods, may call tools)
- Strategies (authored md files — trading rules)
- Market data snapshot (1H candles + 1-minute candles up to session start)

**Resources (on demand):**
- Memory bank (queried only if strategy or skill requires it)
- Previous HTML reports (queried only if strategy or skill requires it)

**Agent tasks (performed independently per ETF):**
1. Regime recognition — identify which strategy fits current market conditions for this ETF (Mean Reversion or Momentum)
2. Signal execution — apply that strategy's rules to generate a decision for this ETF
3. Lot sizing — determine order size within the session money budget
4. Profit target — set a trade-specific profit target based on strategy and market conditions

**Session constraint passed to agent:**
- Session money budget (EUR) — if configured, the agent is informed of this limit before investigation begins so it can factor position sizing into its decision

**Timeout rule:** If investigation does not complete within its budget, the system forces a **Hold** decision and logs a timeout warning to the user.

### 6. Decide
Based on investigation output, the agent produces an independent decision per ETF: **Buy / Sell / Hold**. Each ETF may have a different strategy and different action in the same session.

### 7. Execute
A deterministic execution agent carries out the decided action per ETF via the paper trading API. Execution must complete before the next candle close. If the market closes before execution completes, execution is skipped and logged.

**Session money budget constraint:** The execution workflow checks the agent-decided order value against the session budget before executing. If the order would exceed the budget, execution is skipped and logged.

**Profit target:** Set by the agent per trade during investigation. Stored alongside the position for use by the deterministic exit workflow.

**Stop-loss:** Fixed threshold from config, enforced by the deterministic exit workflow.

### 8. Update Memory
The main agent writes to the shared memory bank and generates an HTML Report.

**Main agent writes:**
- Strategy selected and regime context
- Decision made and reasoning summary
- Session reference (links to HTML report)

**HTML Report (fixed template per strategy) contains:**
- Session number and timestamp
- Strategy identified and reasoning
- Resources consulted
- Investigation summary
- Decision made
- Execution result
- Any warnings (timeout, market closed, skipped)

---

## Memory Bank

A single shared structured store per ETF, written to by both the main agent and the feedback agent. Available on demand to both agents during their respective workflows.

### Purpose
- Track strategy performance over time
- Build context that improves regime recognition
- Store feedback agent evaluations

### Structure

**Strategy performance log**
Per ETF, per strategy — a running record of decisions and outcomes. Queryable by the main agent to answer questions such as: "how has Mean Reversion performed on ETF-1 in the last 10 sessions?"

**Regime context**
A lightweight summary of recent market conditions per ETF, updated each session. Helps the main agent recognize patterns faster without re-reading all HTML reports.

**Feedback evaluations**
Each feedback agent entry stored as a structured record: session reference, thesis, outcome, judgment.

### Write responsibilities

| Writer | What they write |
|---|---|
| Main agent | Decision made, strategy selected per ETF, regime context update, lot size, profit target |
| Feedback agent | Thesis vs outcome evaluation, judgment |

---

## Feedback Loop

Triggered by strategy-dependent timing after the entry session, not on a fixed schedule. Each ETF is evaluated independently based on the strategy used at entry.

| Strategy | Evaluation window |
|---|---|
| Momentum | 1–2 sessions after entry |
| Mean Reversion | 3–6 sessions after entry |

**Workflow:**
```
triggered at strategy-defined window (per ETF)
    → read HTML report from entry session
    → fetch 1H candle close at evaluation time
    → [if needed: run skills to evaluate market state]
    → compare thesis vs outcome
    → write evaluation to memory bank
    → mark ETF position as evaluated → unblock ETF for new trades
```

**Inputs:**
- HTML report from the entry session (what decision was made and why)
- Strategy md file (what "correct" looks like)
- 1H candle close price at evaluation time (what actually happened)
- Skills (on demand, for deeper market state evaluation)

**Role:** Evaluator only. The feedback agent judges whether the thesis was correct and writes its findings to the memory bank. It does not manage positions or trigger execution.

**Retry behavior:** If evaluation fails, the feedback agent retries immediately up to 3 times. After 3 consecutive failures, the evaluation is marked as failed, the ETF is unblocked for new trades, and a warning is logged.

**Position management:** Handled entirely by the deterministic workflow (profit target set by agent at entry, stop-loss threshold from config, evaluation window expiry).

**Position rule:** The main agent cannot open a new position on an ETF until the feedback agent has evaluated and closed the previous trade on that ETF. Each ETF is independent.

**Cross-run carry-over:** Open positions persist in the memory bank across runs. When a new run starts, the system loads any open positions from the memory bank, applies position blocking rules immediately, and resumes stop-loss monitoring at market open for all carried-over positions.

---

## Data Access Pattern

| Data | When fetched | Who uses it |
|---|---|---|
| 1H candles | Session start snapshot | Main agent |
| 1-minute candles | Session start snapshot | Main agent (signal refinement) |
| 1H candle close | At feedback evaluation time | Feedback agent |
| Real-time price | Continuous, deterministic | Stop-loss workflow only |

---

## Agents

| Agent | Type | Responsibility |
|---|---|---|
| Main agent | LLM-assisted | Per-ETF regime recognition, strategy selection, signal execution, lot sizing, profit target setting, decides Buy/Sell/Hold, updates memory |
| Execution agent | Deterministic | Executes Buy/Sell/Hold per ETF via paper trading API, enforces session budget at order time |
| Feedback agent | LLM-assisted | Evaluates thesis vs outcome per ETF at strategy-defined window, writes to memory bank, unblocks ETF after evaluation |
| Deterministic workflow | Deterministic | Stop-loss monitoring (config threshold), profit target exit (agent-set), evaluation window expiry, position closing, carry-over position resumption at market open |

---

## Failure Handling

| Failure | Behavior |
|---|---|
| Fractional session count at startup | Warn user, round down, suggest config adjustment |
| Startup latency exceeds config threshold | Warn user, start anyway, log warning |
| Market closed at execution time | Skip execution, log warning |
| Session timed out (full budget exceeded) | Skip session, log warning, do not count against run total |
| Session money budget exceeded at execution | Skip execution, log warning |
| Market data API unavailable | Force Hold, log warning, skip session, does not count against run total |
| Real-time price feed unavailable | Suspend trading, alert user, resume when feed restored |
| Paper trading API unavailable | Log intended action, skip execution, Hold position, retry next session |
| MCP server (skill) unavailable | Log failed skill, skip investigation, Hold position, retry next session |
| Feedback evaluation failure (≤3 retries) | Retry immediately |
| Feedback evaluation failure (>3 retries) | Mark evaluation as failed, unblock ETF, log warning |

---

## Open Items

- [ ] Define Mean Reversion strategy rules and signals (md file)
- [ ] Define Momentum strategy rules and signals (md file)
- [ ] Define skills required per strategy (md files)
- [ ] Define HTML report template per strategy
- [ ] Framework comparison criteria (latency, verbosity, cost, reliability, tool integration)
