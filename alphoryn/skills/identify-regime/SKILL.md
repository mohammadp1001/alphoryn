---
name: identify-regime
description: Classify the market regime for one ETF as MEAN_REVERSION, MOMENTUM, or NO_REGIME using ADX, EMA structure, MACD, RSI, and Bollinger Band width indicators from the signal snapshot.
---

Follow these steps for each ETF independently.

## Step 1 — Check each regime indicator

Evaluate all eight indicators below. Record each as TRUE or FALSE.

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

## Step 2 — Count agreements

- Count TRUE Momentum indicators → `momentum_score`
- Count TRUE Mean Reversion indicators → `reversion_score`

## Step 3 — Apply decision rule

| Outcome | Condition |
|---|---|
| `MOMENTUM` | `momentum_score >= 3` AND `momentum_score > reversion_score` |
| `MEAN_REVERSION` | `reversion_score >= 3` AND `reversion_score > momentum_score` |
| `NO_REGIME` | Neither score reaches 3, OR both tied at ≥ 3 |

If `NO_REGIME` → output HOLD for this ETF. State the scores in your reasoning.

## Step 4 — State your reasoning

For each ETF, include:
- Each indicator value and TRUE/FALSE (e.g. "ADX = 31.2 → M1 TRUE")
- `momentum_score` and `reversion_score`
- Declared regime and why
- If NO_REGIME: which indicators were ambiguous

## Next step

- MOMENTUM → use `momentum_entry` skill
- MEAN_REVERSION → use `mean_reversion_entry` skill
- NO_REGIME → output HOLD for this ETF; skip entry and sizing
