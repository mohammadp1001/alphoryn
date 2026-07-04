# Skill: Identify Regime

**Used by**: main_agent during investigation, once per ETF per session.
**Input**: `ETFSignals` for one ETF from the `SignalSnapshot`.
**Output**: `MEAN_REVERSION`, `MOMENTUM`, or `NO_REGIME` (→ Hold).

---

## Instructions

Follow these steps for each ETF independently.

### Step 1 — Check each regime indicator

Evaluate the four indicators below. Record each as TRUE or FALSE.

**Momentum indicators** (all four must be checked):

| # | Check | TRUE if |
|---|---|---|
| M1 | ADX trending | `adx_14 > 25` |
| M2 | EMA structure bullish | `ema_20 > ema_50` AND `current_price > ema_20` |
| M3 | MACD bullish | `macd_histogram > 0` |
| M4 | RSI in trend range | `50 <= rsi_14 <= 75` |

**Mean Reversion indicators** (all four must be checked):

| # | Check | TRUE if |
|---|---|---|
| R1 | ADX ranging | `adx_14 < 25` |
| R2 | Price near EMA_20 | `abs(price_vs_ema_20_pct) < 3.0` |
| R3 | Bollinger bands narrow | `(bollinger_upper - bollinger_lower) / sma_20 < 0.04` |
| R4 | RSI in mid-range | `35 <= rsi_14 <= 65` |

### Step 2 — Count agreements

- Count how many Momentum indicators (M1–M4) are TRUE → `momentum_score`
- Count how many Mean Reversion indicators (R1–R4) are TRUE → `reversion_score`

### Step 3 — Apply decision rule

| Outcome | Condition |
|---|---|
| `MOMENTUM` | `momentum_score >= 3` AND `momentum_score > reversion_score` |
| `MEAN_REVERSION` | `reversion_score >= 3` AND `reversion_score > momentum_score` |
| `NO_REGIME` | Neither score reaches 3, OR both scores are equal at ≥ 3 |

If the result is `NO_REGIME`, output **Hold** for this ETF. Do not proceed to entry
evaluation. State the scores in your reasoning.

### Step 4 — State your reasoning

For each ETF, include in your reasoning:
- The value of each indicator (e.g. "ADX = 31.2 → trending")
- The momentum_score and reversion_score
- The declared regime and why
- If NO_REGIME: which indicators were ambiguous

### Example reasoning format

```
ETF: SPY
  M1 ADX=31.2 → TRUE (trending)
  M2 EMA20=541.3 > EMA50=535.1, price=543.0 → TRUE
  M3 MACD histogram=0.42 → TRUE
  M4 RSI=58.3 → TRUE
  momentum_score=4, reversion_score=1
  → MOMENTUM regime declared
```

---

## Next step

- If MOMENTUM → run `momentum_entry` skill
- If MEAN_REVERSION → run `mean_reversion_entry` skill
- If NO_REGIME → output Hold for this ETF, no further evaluation needed
