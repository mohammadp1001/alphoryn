# Skill: Mean Reversion Entry

**Used by**: main_agent after `identify_regime` declares MEAN_REVERSION for an ETF.
**Input**: `ETFSignals` for the ETF. Memory context from `read_memory` skill.
**Output**: Signal strength (`STRONG`, `MODERATE`, `NO_ENTRY`) + profit target value.

---

## Instructions

### Step 1 — Check entry conditions

Evaluate all five conditions. Record each as TRUE or FALSE.

| # | Condition | TRUE if | Signal field |
|---|---|---|---|
| E1 | Price below SMA_20 | `price_vs_sma_20_pct < -1.0` | `price_vs_sma_20_pct` |
| E2 | RSI oversold | `rsi_14 < 40` | `rsi_14` |
| E3 | %B in lower quarter | `bollinger_pct_b < 0.25` | `bollinger_pct_b` |
| E4 | Volume not collapsing | `volume_vs_avg >= 0.7` | `volume_vs_avg` |
| E5 | ADX strongly ranging | `adx_14 < 20` | `adx_14` |

### Step 2 — Count true conditions

`entry_score` = number of TRUE conditions (0–5).

### Step 3 — Apply memory adjustment

Check the memory context from the `read_memory` skill:
- If INCORRECT rate > 60% in the last 5 Mean Reversion trades for this ETF → require
  `entry_score >= 4` for STRONG; `entry_score >= 4` for MODERATE (raise both thresholds by 1)
- Otherwise use standard thresholds below

### Step 4 — Determine signal strength

Standard thresholds:

| Strength | entry_score |
|---|---|
| `STRONG` | 4–5 |
| `MODERATE` | 3 |
| `NO_ENTRY` | < 3 |

If `NO_ENTRY` → output Hold for this ETF. Stop here.

### Step 5 — Set profit target

The profit target is the **current SMA_20 value** (the mean to which price is expected
to revert).

```json
{"type": "price_level", "value": <sma_20>}
```

Record this value. It will be written to `Position.exit_target` on execution.

### Step 6 — State your reasoning

Include in your reasoning:
- Each condition value and TRUE/FALSE (e.g. "price_vs_sma_20_pct = -2.1% → TRUE")
- entry_score and whether memory adjustment was applied
- Signal strength
- Profit target value and why (SMA_20 = X)

### Example reasoning format

```
ETF: QQQ — Mean Reversion Entry
  E1 price_vs_sma_20_pct=-2.1% < -1.0 → TRUE
  E2 rsi_14=36.2 < 40 → TRUE
  E3 bollinger_pct_b=0.18 < 0.25 → TRUE
  E4 volume_vs_avg=0.85 >= 0.7 → TRUE
  E5 adx_14=18.3 < 20 → TRUE
  entry_score=5, no memory adjustment needed
  → STRONG signal
  Profit target: SMA_20=467.32 → {"type": "price_level", "value": 467.32}
```

---

## Next step

- STRONG or MODERATE → run `size_position` skill with this ETF and current_price
- NO_ENTRY → output Hold for this ETF
