# Skill: Momentum Entry

**Used by**: main_agent after `identify_regime` declares MOMENTUM for an ETF.
**Input**: `ETFSignals` for the ETF. Memory context from `read_memory` skill.
**Output**: Entry type (`PULLBACK` or `BREAKOUT`), signal strength (`STRONG`, `MODERATE`, `NO_ENTRY`).

---

## Instructions

Evaluate both entry types. If both qualify, prefer PULLBACK (lower risk). If neither
qualifies, output Hold for this ETF.

---

### Entry Type A: Pullback

#### Step A1 — Check pullback conditions

| # | Condition | TRUE if | Signal field |
|---|---|---|---|
| P1 | Price near EMA_20 | `-2.0 <= price_vs_ema_20_pct <= 0.5` | `price_vs_ema_20_pct` |
| P2 | Trend structure intact | `ema_20 > ema_50` | `ema_20`, `ema_50` |
| P3 | MACD positive | `macd_histogram > 0` | `macd_histogram` |
| P4 | RSI not overbought | `rsi_14 < 70` | `rsi_14` |
| P5 | ADX strong | `adx_14 > 25` | `adx_14` |

#### Step A2 — Pullback signal strength

| Strength | Conditions met |
|---|---|
| `STRONG` | 5 |
| `MODERATE` | 4 |
| `NO_ENTRY` | < 4 |

---

### Entry Type B: Breakout

#### Step B1 — Check breakout conditions

| # | Condition | TRUE if | Signal field |
|---|---|---|---|
| B1 | Price above upper band | `bollinger_pct_b > 1.0` | `bollinger_pct_b` |
| B2 | Volume surge | `volume_vs_avg >= 1.5` | `volume_vs_avg` |
| B3 | MACD accelerating | `macd_histogram > 0` AND `macd_line > 0` | `macd_histogram`, `macd_line` |
| B4 | RSI confirming | `rsi_14 >= 60` | `rsi_14` |
| B5 | ADX strong | `adx_14 > 28` | `adx_14` |

#### Step B2 — Breakout signal strength

| Strength | Conditions met |
|---|---|
| `STRONG` | 5 |
| `MODERATE` | 4 |
| `NO_ENTRY` | < 4 |

---

### Step C — Apply memory adjustment

Check the memory context from the `read_memory` skill:
- If INCORRECT rate > 60% in the last 5 Momentum trades for this ETF → only accept
  STRONG signals. Downgrade MODERATE to NO_ENTRY.

---

### Step D — Select entry type

1. If Pullback qualifies (STRONG or MODERATE after memory adjustment) → use PULLBACK
2. Else if Breakout qualifies → use BREAKOUT
3. Else → NO_ENTRY → output Hold for this ETF

---

### Step E — State your reasoning

Include in your reasoning:
- Each condition value and TRUE/FALSE for both entry types evaluated
- Which entry type was selected and why
- Signal strength after memory adjustment

### Example reasoning format

```
ETF: SPY — Momentum Entry
  Pullback check:
    P1 price_vs_ema_20_pct=+0.3% → TRUE
    P2 ema_20=541.3 > ema_50=535.1 → TRUE
    P3 macd_histogram=0.42 → TRUE
    P4 rsi_14=58.3 < 70 → TRUE
    P5 adx_14=31.2 > 25 → TRUE
    pullback_score=5 → STRONG
  Breakout check: skipped (Pullback already qualifies)
  Memory: 2/4 recent INCORRECT, no adjustment needed
  → PULLBACK STRONG
```

---

## Next step

- STRONG or MODERATE → run `size_position` skill with this ETF and current_price
- NO_ENTRY → output Hold for this ETF
