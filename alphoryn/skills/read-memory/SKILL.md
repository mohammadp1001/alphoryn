---
name: read-memory
description: Summarise recent trade performance for an ETF and strategy combination from the memory entries provided in context, and flag whether a stricter entry signal threshold should apply.
---

**When to use**: At the start of investigation for each ETF, once the regime is identified.

## Step 1 — Locate relevant memory entries

From the `memory_entries` provided in the session context, filter to entries matching:
- `etf` == this ETF ticker
- `strategy` == identified regime (MEAN_REVERSION or MOMENTUM)

Take the most recent 5 entries ordered by `created_at` descending.

Fields to examine per entry:
- `decision` — BUY, SELL, or HOLD
- `outcome_judgment` — CORRECT, INCORRECT, NEUTRAL, or null (not yet evaluated)
- `regime_context` — JSON summary of market conditions at entry

## Step 2 — Count evaluated outcomes

From entries where `outcome_judgment` is not null:

```
correct_count   = count where outcome_judgment == "CORRECT"
incorrect_count = count where outcome_judgment == "INCORRECT"
total_evaluated = correct_count + incorrect_count  (exclude NEUTRAL and null)
```

If `total_evaluated == 0` → no adjustment needed, proceed normally.

## Step 3 — Compute incorrect rate

```
incorrect_rate = incorrect_count / total_evaluated
```

If `incorrect_rate > 0.60` → set `memory_adjustment = True` (stricter entry threshold required).
Otherwise → `memory_adjustment = False`.

## Step 4 — Compose memory summary (1–2 sentences)

- No prior trades: `"No prior {strategy} trades for {etf} to reference."`
- Adjustment active: `"Recent {strategy} on {etf}: {incorrect_count}/{total_evaluated} incorrect — requiring stronger entry signal."`
- No adjustment: `"Recent {strategy} on {etf}: {correct_count}/{total_evaluated} correct."`

## Step 5 — Pass outputs to entry skill

Pass `memory_adjustment` (bool) and `memory_summary` (str) to the relevant entry skill (`mean-reversion-entry` or `momentum-entry`). Include `memory_summary` in the final `reasoning` field of the ETFDecision.
