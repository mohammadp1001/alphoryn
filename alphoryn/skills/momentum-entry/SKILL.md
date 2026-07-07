---
name: momentum-entry
description: Evaluate momentum entry conditions for one ETF after identify-regime declares MOMENTUM. Checks Pullback and Breakout entry types, applies memory adjustment, and outputs entry type and signal strength (STRONG, MODERATE, or NO_ENTRY).
---

**Prerequisite**: `identify-regime` must have returned MOMENTUM for this ETF.

Evaluate both entry types. If both qualify, prefer PULLBACK (lower risk).

## Entry Type A: Pullback

### Step A1 — Check pullback conditions

| # | Condition | TRUE if | Signal field |
|---|---|---|---|
| P1 | Price near EMA_20 | `-2.0 <= price_vs_ema_20_pct <= 0.5` | `price_vs_ema_20_pct` |
| P2 | Trend structure intact | `ema_20 > ema_50` | `ema_20`, `ema_50` |
| P3 | MACD positive | `macd_histogram > 0` | `macd_histogram` |
| P4 | RSI not overbought | `rsi_14 < 70` | `rsi_14` |
| P5 | ADX strong | `adx_14 > 25` | `adx_14` |

### Step A2 — Pullback signal strength

| Strength | Conditions met |
|---|---|
| `STRONG` | 5 |
| `MODERATE` | 4 |
| `NO_ENTRY` | < 4 |

## Entry Type B: Breakout

### Step B1 — Check breakout conditions

| # | Condition | TRUE if | Signal field |
|---|---|---|---|
| B1 | Price above upper band | `bollinger_pct_b > 1.0` | `bollinger_pct_b` |
| B2 | Volume surge | `volume_vs_avg >= 1.5` | `volume_vs_avg` |
| B3 | MACD accelerating | `macd_histogram > 0` AND `macd_line > 0` | `macd_histogram`, `macd_line` |
| B4 | RSI confirming | `rsi_14 >= 60` | `rsi_14` |
| B5 | ADX strong | `adx_14 > 28` | `adx_14` |

### Step B2 — Breakout signal strength

| Strength | Conditions met |
|---|---|
| `STRONG` | 5 |
| `MODERATE` | 4 |
| `NO_ENTRY` | < 4 |

## Step C — Apply memory adjustment

Check the memory summary from `read-memory`:
- If INCORRECT rate > 60% in last 5 Momentum trades for this ETF → downgrade MODERATE to NO_ENTRY (only accept STRONG signals).

## Step D — Select entry type

1. Pullback qualifies (STRONG or MODERATE after adjustment) → use PULLBACK
2. Else breakout qualifies → use BREAKOUT
3. Else → NO_ENTRY → output HOLD for this ETF

## Step E — State your reasoning

Include:
- Each condition value and TRUE/FALSE for both entry types
- Which entry type was selected and why
- Signal strength after memory adjustment

## Next step

- STRONG or MODERATE → use `size-position` skill with this ETF and `current_price`
- NO_ENTRY → output HOLD for this ETF
