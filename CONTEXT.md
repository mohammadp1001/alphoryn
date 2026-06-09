---
name: algotrade-agent
description: Autonomous ETF trading agent — domain language and canonical terms
---

# AlgoTrade Agent — Domain Context

## MarketRegime

A typed enum classifying the current macro/price environment. Computed **once per session** by `research.summarize_market_regime`, stored on `PlanState`, and treated as immutable for the duration of that session.

**Valid values:**
- `BULL_TREND` — sustained upward price action, positive breadth
- `BEAR_TREND` — sustained downward price action, negative breadth
- `HIGH_VOL` — elevated implied/realised volatility regardless of direction
- `LOW_VOL_RANGE` — compressed volatility, price oscillating within a range
- `CRISIS` — extreme dislocation (VIX spike, circuit breakers, macro shock)

**Owner:** Research agent. Returns `MarketRegimeSummary` with a `.regime: MarketRegime` field. The coordinator reads `.regime` off `PlanState` for every calibration lookup and regime-stats write.

**Stability:** Fixed per session. If a session spans multiple days, the regime is the one classified at session start.

## ETF Universe

The set of instruments `market.screen_etfs` operates on. Defined as `DEFAULT_ETF_UNIVERSE` in config — a hardcoded baseline of 17 liquid ETFs:

**Sector (SPDR 11):** XLK, XLE, XLF, XLV, XLY, XLP, XLI, XLB, XLU, XLRE, XLC

**Broad market (6):** SPY, QQQ, IWM, GLD, TLT, VNQ

No leveraged, inverse, or illiquid ETFs in the default list. The user can extend the universe via `config.json` but cannot shrink below the default without editing the file directly. `market.screen_etfs` always filters within the active universe — it never queries Alpaca's full instrument list.

## Target Market

**ETFs only.** Forex has been cut from scope. The session parameter `target_market` is removed — it was the only field that referenced Forex. Noted in MEMO.md as a future direction alongside streaming data and web UI.

## Strategy

A typed enum stored on `PlanState` that drives actual agent behaviour — not just a calibration label.

**Values:** `MOMENTUM`, `MEAN_REVERSION`, `SECTOR_ROTATION`

**Effect on analysis agent:** The active strategy is included in the analysis agent's system prompt, biasing which indicators it weights when computing `TechnicalScore` and `RankedSignals`:
- `MOMENTUM` → weight RSI momentum, MACD crossovers, volume breakouts
- `MEAN_REVERSION` → weight Bollinger Band position, support/resistance levels, RSI overbought/oversold
- `SECTOR_ROTATION` → weight relative sector performance, fund flows, benchmark comparison

**Effect on execution agent:** Determines default order type:
- `MOMENTUM` → market orders (execution speed matters)
- `MEAN_REVERSION` → limit orders (entry price matters)
- `SECTOR_ROTATION` → limit orders (rebalancing is not time-critical)

**Effect on calibration:** Win rates in `agent_pairwise` and `regime_stats` are keyed per `(agent, market_regime, strategy)` — strategy differences are meaningful because the agent actually behaves differently.

## Session

A single CLI invocation. Begins when the user starts the process, ends when they type `exit`, the loss limit hits 100%, or the process is killed.

- **`session_id`:** UUID generated at session start. Every invocation is a new session — no resumption across invocations.
- **Timeframe (1 / 3 / 5 days):** the *lookback window for technical analysis* (how much historical OHLCV data to feed indicators), not a multi-day session duration.
- **Session close:** clean exit writes `closed_at` to the `sessions` table. Unclean exits leave `closed_at` null — detected at next session start, marked `outcome_timed_out`.
- **Loss limit scope:** realised P&L from trades where `session_id = current session UUID` only.

**`sessions` table:** `id (UUID PK)`, `started_at`, `closed_at`, `strategy`, `market_regime`, `mode`, `realised_pnl`, `cycle_count`, `outcome (clean | loss_limit | killed | timed_out)`.

## User Profile

Split across two stores by purpose:

- **`~/.algotrade/config.json`** — API key references (GCP Secret Manager resource names, not values) and user preference defaults (strategy, timeframe, loss limit, shortlist N, HITL timeout, mode). Safe to inspect; contains no secrets.
- **SQLite `sessions` table** — session history: `id, started_at, strategy, market_regime, mode, realised_pnl, cycle_count, outcome`. Never in the config file.

**First-run wizard:** writes `config.json`, validates that Secret Manager references resolve, and confirms Alpaca paper trading connectivity.

**Session start — existing portfolio load:** before the first decision cycle, the coordinator calls `execution.get_positions` and `execution.get_portfolio` to load the user's existing Alpaca paper portfolio into `PlanState`. This snapshot is used for: loss limit baseline, position sizing, and avoiding duplicate positions in the candidate shortlist. If the user already holds XLK, the analysis agent's output is still unfiltered — but the coordinator factors the existing position into the shortlist reasoning.

## PlanState

The coordinator's single source of truth across a session. Holds: active strategy, session parameters (timeframe, loss limit, mode), current `MarketRegime`, candidate shortlist, and last `RiskAssessment`. Passed forward through every decision cycle. Never shared with subagents directly — subagents receive only the inputs relevant to their task.

## Decision Cycle

One complete pass: screen → research → analyse → debate → execute. The unit of context compaction.

Every cycle ends in one of two states stored on `PlanState.cycle_history`:

- **`COMMITTED`** — execution agent wrote a `TradeRecord`. Full cycle summary is compacted: instruments, signals, debate verdict, order details.
- **`ABORTED`** — cycle ended without a trade for any reason (HITL rejected, HITL timeout, no viable signals, execution error, HIGH risk in full-auto). Brief summary is compacted recording the abort reason and the stage at which it stopped (e.g. `"HITL rejected at HIGH risk — XLK, XLE shortlisted"`).

`summarize_context()` runs after **both** outcomes. Aborted cycles are never silently discarded — the coordinator uses `cycle_history` when reasoning about why previous attempts failed.

## CandidateShortlist

The top-N ETFs selected by the coordinator from the analysis agent's `RankedSignals`. This list — not the full universe — is the shared input to both risk agents.

N is a **fixed session parameter** (set at session start alongside timeframe, strategy, loss limit). Default = 2, max = 5. The coordinator reasons about *which* N to select from the ranked list, but not *how many*. Keeping N small (default 2) forces the debate to argue deeply about specific instruments rather than shallowly across many.

## RiskAssessment

The coordinator's synthesised verdict after the risk debate. Fields: `level: LOW | MEDIUM | HIGH`, `recommended_action`, `synthesis_reasoning`.

**Synthesis is deterministic (coded, not LLM-driven):**
1. Map verdicts to integers: `LOW=0, MEDIUM=1, HIGH=2`
2. Weighted score = `(opt_level × opt_win_rate + pess_level × pess_win_rate) / (opt_win_rate + pess_win_rate)`
3. Thresholds: score < 0.6 → LOW · 0.6–1.2 → MEDIUM · > 1.2 → HIGH
4. **Asymmetric override:** if `pessimist_win_rate > 0.65` AND pessimist verdict is HIGH → level is always HIGH regardless of weighted score (loss aversion)
5. On cold start (no calibration data): weights are equal (0.5 / 0.5); override inactive

The LLM writes `synthesis_reasoning` — but `level` is computed by the formula. HIGH always triggers HITL regardless of operating mode.

## Loss Limit

A hard cap on realised P&L loss within a single session, set by the user at session start (in EUR).

**Measured against:** realised losses from trades with `session_id = current` only. Unrealised (open position) losses are excluded.

**Two-layer enforcement:**
1. Coordinator checks cumulative session P&L via `memory.get_cycle_history` before spawning the execution agent
2. Execution agent independently re-checks via `execution.get_portfolio` before placing any order
Both layers must pass independently — neither trusts the other.

**Thresholds:**
- > 80% consumed → HITL triggered (user confirmation required before proceeding)
- 100% consumed → session halts immediately. No new orders. Agent surfaces a summary and exits cleanly. Open positions are **not** automatically closed — that is the user's decision.

## HITL (Human-in-the-Loop)

A blocking pause that surfaces a proposed action to the user for y/n confirmation. Triggered by: every proposed order in semi-auto mode; `RiskAssessment.level == HIGH` in full-auto; session loss limit > 80% consumed. Timeout defaults to 60 s → abort.

## Observability

Two-tier instrumentation rule using Cloud Trace + Cloud Logging. Every session has a unique trace ID.

**Gets a trace span** (timing matters or crosses a boundary):
- Each decision cycle — parent span
- Each subagent spawn + response — child span
- Each external API call (Alpaca data, Alpaca trading, yfinance, Secret Manager) — child span
- HITL prompt + user response — child span (measures user latency)
- SQLite writes for `TradeRecord` and outcome resolution — child span

**Gets a log entry only:**
- Session start/end with parameters
- Every coordinator decision with reasoning
- Every HITL prompt and response
- Every cycle abort with reason and stage
- Every rate-limit hit and retry
- Loss limit percentage at each cycle

**Not instrumented** (internal, synchronous, cheap):
- Individual indicator computations (RSI, MACD, Bollinger, etc.)
- In-memory `PlanState` reads/writes
- Config file reads

Target: 8–15 spans per decision cycle. Traces stay readable; logs carry the full narrative.

## Rate Limiting

One token-bucket rate limiter per external API, implemented in `infra/rate_limiter.py`:

| Limiter | Rate | Burst | Rationale |
|---|---|---|---|
| `alpaca_data` | 200 req/min | 10 | Alpaca free tier hard limit |
| `alpaca_trading` | 10 req/min | 3 | Conservative — no official paper limit, prevents runaway orders |
| `yfinance` | 2 req/sec | 3 | IP-block avoidance |
| `secret_manager` | 10 req/min | 2 | Safety floor — called rarely |

**Retry policy:** exponential backoff with jitter, max 3 retries, on HTTP 429 and 5xx only. Applied as decorator `@with_retry` in `infra/retry.py`. Not applied to trading order placement — a retry on a failed order risks double-execution.

## Execution Secret Isolation

The Alpaca execution API key is fetched from GCP Secret Manager by the **coordinator's harness** at execution-agent spawn time and injected as environment variables (`ALPACA_API_KEY`, `ALPACA_API_SECRET`) into the execution agent's context only. The coordinator reads the secret value solely to pass it forward — it must not log it, store it on `PlanState`, or pass it to any other subagent.

Single GCP service account across the whole system (demo-scope simplification). Isolation is enforced **by code boundary and convention**, not by separate IAM roles. The trade-off is documented in [[ADR 0002]].

## Write-Ahead Pattern

The execution agent writes a `TradeRecord` to SQLite **before** returning `OrderResult` to the coordinator. This collapses the window between "order exists in Alpaca" and "system knows about it" to zero. Outcome fields (`actual_pnl_pct`, `debate_winner`, `outcome_resolved`) are filled later via event-driven outcome resolution.

## Outcome Resolution

The process of filling `actual_pnl_pct`, `debate_winner`, and `outcome_resolved=1` on a `TradeRecord` after a position closes.

**Primary path:** Alpaca webhook (`order_fill` / `position_closed` events) → lightweight Cloud Run HTTP endpoint → writes to SQLite directly.

**Fallback path (polling):** Runs at **session start only** — the coordinator checks all `outcome_resolved=0` records, queries Alpaca for current position status, and resolves any that have closed. No background daemon required.

**Outcome definition:** Position fully closed (0 shares remaining in Alpaca for that symbol).

**Cutoff:** If a trade is still open beyond `session_timeframe + 1 day`, it is marked `outcome_timed_out` and excluded from win-rate calculations. Ambiguous data does not pollute calibration.

## Eval Scenario

A YAML file in `evals/scenarios/` that provides everything the agent normally gets from live APIs, enabling deterministic harness replay without hitting Alpaca or yfinance.

**Required fields:**
- `id` — unique scenario identifier
- `description` — what the scenario tests and what the expected winner is
- `session_params` — strategy, timeframe, shortlist_n, loss_limit_eur
- `market_regime` — the regime classification for this scenario
- `ohlcv_fixtures` — pre-captured OHLCV bars per symbol (full ETF universe)
- `news_fixtures` — pre-captured news items per symbol
- `expected_outcome` — `debate_winner`, `risk_level`, `forward_return_pct` (ground truth for Gemini Pro judge)

The harness replaces all API calls with fixture data, runs agent version A and B against the same scenario, sends both decisions to Gemini Pro judge with rubric, records win/loss/tie. Scenario files are built by recording real API responses — `evals/record_scenario.py` is a helper script that captures a live session's API calls into a fixture file.

## Signal Lookback (BacktestResult)

The output of `analysis.run_backtest(RankedSignals, strategy)`. Not a full portfolio simulation — a **signal-match summary**: for each candidate ETF, look back over the last N bars and measure the average forward return on historical occurrences of a signal similar to the current one.

**What it computes:** "Historically, when the current signal pattern occurred on this instrument in this regime, what was the average 3-day forward return, and how often was it positive?"

**Fields:** `symbol`, `signal_pattern`, `lookback_bars`, `match_count`, `avg_forward_return_pct`, `win_rate_pct`, `max_adverse_excursion_pct`

**Honest scope:** documents as a signal lookback, not a full backtest. Lookahead bias and survivorship bias are not modelled. Noted in MEMO.md.

## Tool Registry

**60 tools across 6 namespaces.** All tools originate from one central `registry.py`. Subagents receive a filtered slice.

| Namespace | Count | Scope |
|---|---|---|
| `coordinator.*` | 5 | Coordinator only — `spawn_research_agent`, `spawn_analysis_agent`, `spawn_risk_debate`, `spawn_execution_agent`, `request_hitl` |
| `memory.*` | 3 | Coordinator only — `get_calibration`, `resolve_outcome`, `get_cycle_history` |
| `market.*` | 12 | Analysis agent |
| `analysis.*` | 14 | Analysis agent |
| `research.*` | 14 | Research agent |
| `execution.*` | 12 | Execution agent |

Risk agents receive no tools from the registry — they operate on injected context only (shortlist + backtest result + sentiment report + calibration context).

## Memory Tools

A coordinator-only namespace (`memory.*`). Risk agents never call memory tools — they receive calibration as **injected context** prepended to their system prompt by the coordinator before spawn. This keeps subagent registries clean and makes the injection point explicit and testable.

**Tools:**
- `memory.get_calibration(agent, market_regime, strategy)` → `CalibrationContext` — reads `agent_pairwise` for the current session key
- `memory.resolve_outcome(trade_id, actual_pnl_pct)` → `UpdateResult` — fills outcome fields on a `TradeRecord` and updates `agent_pairwise`
- `memory.get_cycle_history(session_id)` → `list[CycleRecord]` — returns `PlanState.cycle_history` for coordinator reasoning

No other agent has access to `memory.*` tools.

## Pairwise Win-Rate

The calibration metric used to weight the risk debate. After each trade's outcome resolves, the system records which agent's recommendation was vindicated. Win rate = wins / (wins + losses). Stored in `agent_pairwise` keyed by `(agent, market_regime, strategy)`. Calibration injection is skipped until at least 1 completed head-to-head comparison exists for the current key — both agents start at equal weight (honest prior, no fabricated priors).

## Debate Winner

Determined when a trade's outcome resolves. Rules are **asymmetric** (consistent with loss aversion in [[RiskAssessment]] synthesis):

- `actual_pnl_pct >= DEBATE_TIE_THRESHOLD_PCT (0.5%)` → optimist wins
- `actual_pnl_pct < 0` (any loss) → pessimist wins, no lower tie band
- `0 <= actual_pnl_pct < 0.5%` → tie

`DEBATE_TIE_THRESHOLD_PCT = 0.5` is a named constant in config, not hardcoded. The pessimist's recommendation is directionally "don't trade / reduce size", not "go short" — a small gain does not vindicate the optimist.
