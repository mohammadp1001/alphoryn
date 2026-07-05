# Strategy: Momentum

## Overview

Momentum assumes that assets trending strongly will continue in the same direction.
The strategy buys during confirmed uptrends on either a pullback to the EMA_20 or a
volume-confirmed breakout above the upper Bollinger Band. Exit is managed by a trailing
stop that locks in gains as price rises.

---

## Regime Recognition

Momentum requires a trending market — strong directional movement with price leading
the moving averages.

| Indicator | Condition | Signal field |
|---|---|---|
| ADX | `adx_14 > 25` | `adx_14` |
| EMA structure | `ema_20 > ema_50` AND `current_price > ema_20` | `ema_20`, `ema_50`, `current_price` |
| MACD | `macd_histogram > 0` (MACD line above signal line) | `macd_histogram` |
| RSI trend | `50 <= rsi_14 <= 75` (bullish but not overbought) | `rsi_14` |

**Decision rule**: At least 3 of 4 conditions must be TRUE for Momentum regime to be
declared. Checked by the `identify_regime` skill before entry evaluation.

---

## Entry Signal

Two valid entry types. Only one needs to qualify — evaluate both and use whichever
meets its threshold; prefer Pullback if both qualify.

### Entry Type A: Pullback

Price has pulled back to the EMA_20 within an established uptrend — a lower-risk entry
point with the trend intact.

| Condition | Threshold | Signal field |
|---|---|---|
| Price near EMA_20 | `-2.0 <= price_vs_ema_20_pct <= 0.5` (within 2% below to 0.5% above) | `price_vs_ema_20_pct` |
| Trend structure intact | `ema_20 > ema_50` | `ema_20`, `ema_50` |
| MACD positive | `macd_histogram > 0` | `macd_histogram` |
| RSI not overbought | `rsi_14 < 70` | `rsi_14` |
| ADX strong | `adx_14 > 25` | `adx_14` |

**Signal strength**:
- **STRONG**: all 5 conditions met
- **MODERATE**: 4 conditions met
- **NO_ENTRY**: fewer than 4

### Entry Type B: Breakout

Price has broken above the upper Bollinger Band with confirming volume — a higher-momentum
entry suited to early trend acceleration.

| Condition | Threshold | Signal field |
|---|---|---|
| Price above upper band | `bollinger_pct_b > 1.0` | `bollinger_pct_b` |
| Volume surge | `volume_vs_avg >= 1.5` (at least 50% above average) | `volume_vs_avg` |
| MACD accelerating | `macd_histogram > 0` AND `macd_line > 0` | `macd_histogram`, `macd_line` |
| RSI confirming | `rsi_14 >= 60` | `rsi_14` |
| ADX strong | `adx_14 > 28` | `adx_14` |

**Signal strength**:
- **STRONG**: all 5 conditions met
- **MODERATE**: 4 conditions met
- **NO_ENTRY**: fewer than 4

---

## Profit Target (Trailing Stop)

A trailing stop locks in gains as price rises. The monitor tracks a high watermark and
updates the stop price dynamically.

```json
{"type": "trailing_stop", "trail_pct": 0.015}
```

**Trailing stop mechanics** (implemented in `monitor/monitor.py`):

```
At each poll cycle:
  if current_price > trailing_stop_high_watermark:
      trailing_stop_high_watermark = current_price   # update Position record
  
  trailing_stop_price = trailing_stop_high_watermark * (1 - trail_pct)
  
  if current_price <= trailing_stop_price:
      if trailing_stop_price > entry_price:
          close position → exit_reason = PROFIT_TARGET   # locked in gain
      else:
          close position → exit_reason = STOP_LOSS       # hard floor applies
```

`trailing_stop_high_watermark` is stored in the Position record and updated by the
monitor on each poll cycle when a new high is reached. Initialized to `entry_price` at
position creation.

---

## Stop Loss (Hard Floor)

The global `stop_loss_pct` config is the hard floor and takes precedence if the trailing
stop has not yet risen above the entry price.

```
hard_stop_price = entry_price * (1 - stop_loss_pct)
```

The monitor checks `hard_stop_price` independently on every poll. If
`current_price <= hard_stop_price` and `trailing_stop_price <= entry_price`, the position
closes with `exit_reason = STOP_LOSS`. Once the trailing stop has risen above `entry_price`,
the trailing stop is the operative floor and `hard_stop_price` is no longer checked.

---

## Exit Conditions

| Condition | Trigger | Exit reason |
|---|---|---|
| Trailing stop (gain) | Trailing stop triggers above entry price | `PROFIT_TARGET` |
| Hard stop / trailing stop (loss) | Price ≤ hard_stop_price OR trailing stop triggers at/below entry | `STOP_LOSS` |
| Window expiry | Session ordinal reaches `evaluation_window_session` | `WINDOW_EXPIRY` |

---

## Evaluation Window

**2 sessions after the position closes.**

`evaluation_window_session = entry_session_ordinal + 2`

Momentum trades resolve quickly — price either continues in the trend direction or
reverses. Two sessions is sufficient to determine whether the thesis held.

---

## Feedback Evaluation Criteria

The feedback agent compares:
- **Thesis**: a confirmed uptrend (Pullback or Breakout entry) was expected to continue
- **Outcome**: did price move meaningfully in the trend direction before or at evaluation time?
- **Judgment**:
  - `CORRECT` — position closed at PROFIT_TARGET, or price at evaluation is ≥ 2% above entry
  - `INCORRECT` — position closed at STOP_LOSS, or price at evaluation is below entry
  - `NEUTRAL` — position closed at WINDOW_EXPIRY with gain < 2%
