---
name: mean-reversion-entry
description: Evaluate mean reversion entry conditions for one ETF after identify-regime declares MEAN_REVERSION. Outputs signal strength (STRONG, MODERATE, or NO_ENTRY) and the profit target price level.
---

**Prerequisite**: `identify-regime` must have returned MEAN_REVERSION for this ETF.

## Step 1 — Check entry conditions

Evaluate all five conditions. Record each as TRUE or FALSE.

| # | Condition | TRUE if | Signal field |
|---|---|---|---|
| E1 | Price below SMA_20 | `price_vs_sma_20_pct < -1.0` | `price_vs_sma_20_pct` |
| E2 | RSI oversold | `rsi_14 < 40` | `rsi_14` |
| E3 | %B in lower quarter | `bollinger_pct_b < 0.25` | `bollinger_pct_b` |
| E4 | Volume not collapsing | `volume_vs_avg >= 0.7` | `volume_vs_avg` |
| E5 | ADX strongly ranging | `adx_14 < 20` | `adx_14` |

`entry_score` = count of TRUE conditions (0–5).

## Step 2 — Apply memory adjustment

Check the memory summary from `read-memory`:
- If INCORRECT rate > 60% in last 5 Mean Reversion trades for this ETF → raise both thresholds by 1 (STRONG requires 5, MODERATE requires 4).
- Otherwise use standard thresholds.

## Step 3 — Determine signal strength

Standard thresholds:

| Strength | entry_score |
|---|---|
| `STRONG` | 4–5 |
| `MODERATE` | 3 |
| `NO_ENTRY` | < 3 |

If `NO_ENTRY` → output HOLD for this ETF. Stop here.

## Step 4 — Set profit target

The profit target is the current SMA_20 value (price is expected to revert to the mean):

```json
{"type": "price_level", "value": <sma_20>}
```

## Step 5 — State your reasoning

Include:
- Each condition value and TRUE/FALSE
- `entry_score` and whether memory adjustment was applied
- Signal strength
- Profit target value

## Next step

- STRONG or MODERATE → use `size-position` skill with this ETF and `current_price`
- NO_ENTRY → output HOLD for this ETF
