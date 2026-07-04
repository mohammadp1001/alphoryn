# Skill: Size Position

**Used by**: main_agent after a STRONG or MODERATE entry signal has been confirmed.
**Input**: ETF ticker, `current_price`, session money budget (from config or account equity).
**Output**: `lot_size` (integer shares) or downgrade to Hold if cannot buy 1 share.

---

## Instructions

### Step 1 — Determine available budget

Check the session money budget in order of precedence:

1. If `session_money_budget` is set in config (not null): use that value in USD.
2. If `session_money_budget` is null: use **5% of current account equity**.
   - Account equity is available from the Alpaca account info (fetched pre-investigation
     by the execution agent; passed to the agent as context).

Call this value `available_budget`.

### Step 2 — Calculate maximum shares

```
max_shares = floor(available_budget / current_price)
```

Use integer division — always round down. Never buy fractional shares.

### Step 3 — Check minimum

If `max_shares < 1`:
- Output: **downgrade this ETF decision to Hold**
- State in reasoning: "Budget of $X insufficient to buy 1 share at $Y — Hold."
- Stop here.

### Step 4 — Apply per-ETF budget cap

If two ETFs are both buying in the same session, the budget must be split. Apply a
per-ETF cap of 60% of `available_budget` so neither ETF consumes the full budget.

```
per_etf_budget = min(available_budget, available_budget * 0.60)
lot_size = floor(per_etf_budget / current_price)
```

If after the cap `lot_size < 1` → downgrade to Hold (same as Step 3).

### Step 5 — State your reasoning

Include in your reasoning:
- Budget source (config or 5% of equity) and USD amount
- current_price
- Calculated lot_size
- Whether the per-ETF cap was applied

### Example reasoning format

```
ETF: SPY — Position Sizing
  Budget source: session_money_budget = $5000.00 (from config)
  current_price = $543.21
  max_shares = floor(5000 / 543.21) = 9
  Per-ETF cap (60%): floor(3000 / 543.21) = 5
  Both ETFs buying this session → applying cap
  → lot_size = 5 shares
```

---

## Output

Pass `lot_size` to the final decision output as part of `ETFDecision.lot_size`.
The execution agent will validate budget again at order time before placing the order.
