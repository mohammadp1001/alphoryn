---
name: size-position
description: Calculate the integer lot size for a trade given the available session budget and current price, applying a per-ETF 60% cap when both ETFs are buying in the same session.
---

**Prerequisite**: Entry signal must be STRONG or MODERATE from the relevant entry skill.

## Step 1 — Determine available budget

1. If `session_money_budget` is set in config (not null) → use that value in USD.
2. If null → use 5% of current account equity.

Call this value `available_budget`.

## Step 2 — Calculate maximum shares

```
max_shares = floor(available_budget / current_price)
```

Always round down — never buy fractional shares.

## Step 3 — Check minimum

If `max_shares < 1`:
- Downgrade this ETF decision to HOLD
- State in reasoning: "Budget of $X insufficient to buy 1 share at $Y — Hold."
- Stop here.

## Step 4 — Apply per-ETF budget cap

If both ETFs are buying in the same session, cap each at 60% of `available_budget`:

```
per_etf_budget = available_budget * 0.60
lot_size = floor(per_etf_budget / current_price)
```

If after the cap `lot_size < 1` → downgrade to HOLD (same as Step 3).

## Step 5 — State your reasoning

Include:
- Budget source and USD amount
- `current_price`
- Calculated `lot_size`
- Whether the per-ETF 60% cap was applied

## Output

Pass `lot_size` to the final SessionDecision as `ETFDecision.lot_size`.
The execution agent will re-validate budget at order time.
