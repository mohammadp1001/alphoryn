# Strategy: Mean Reversion

## Overview

Mean Reversion assumes that prices oscillate around a stable mean and that deviations
will revert. The strategy buys when price is meaningfully below the 20-period SMA in a
ranging (non-trending) market, targeting a return to the mean.

---

## Regime Recognition

Mean Reversion requires a ranging market — low directional momentum, price oscillating
around the SMA rather than trending away from it.

| Indicator | Condition | Signal field |
|---|---|---|
| ADX | `adx_14 < 25` | `adx_14` |
| EMA structure | `abs(price_vs_ema_20_pct) < 3.0` (price within 3% of EMA_20) | `price_vs_ema_20_pct` |
| Bollinger Band width | `(bollinger_upper - bollinger_lower) / sma_20 < 0.04` (bands within 4% of SMA) | `bollinger_upper`, `bollinger_lower`, `sma_20` |
| RSI range | `35 <= rsi_14 <= 65` (mid-range, not extended in either direction) | `rsi_14` |

**Decision rule**: At least 3 of 4 conditions must be TRUE for Mean Reversion regime to
be declared. Checked by the `identify_regime` skill before entry evaluation.

---

## Entry Signal

Entry is long-only (BUY). Triggered when price has pulled below the mean and conditions
favour reversion upward.

| Condition | Threshold | Signal field |
|---|---|---|
| Price below SMA_20 | `price_vs_sma_20_pct < -1.0` (at least 1% below SMA) | `price_vs_sma_20_pct` |
| RSI oversold | `rsi_14 < 40` | `rsi_14` |
| Bollinger %B low | `bollinger_pct_b < 0.25` (price in lower quarter of bands) | `bollinger_pct_b` |
| Volume not collapsing | `volume_vs_avg >= 0.7` (at least 70% of average — confirms active market) | `volume_vs_avg` |
| ADX weak | `adx_14 < 20` (strongly ranging — tighter than regime threshold) | `adx_14` |

**Signal strength**:
- **STRONG**: 4–5 conditions met → proceed to position sizing
- **MODERATE**: 3 conditions met → proceed to position sizing with reduced conviction
- **NO_ENTRY**: fewer than 3 → Hold for this ETF this session

The mean_reversion_entry skill computes this score and outputs strength + profit target.

---

## Profit Target

The 20-period SMA at the time of entry is the profit target (price is expected to revert
to the mean).

```json
{"type": "price_level", "value": <sma_20 at entry time>}
```

The agent sets `exit_target` to this value when writing the Position record.

---

## Stop Loss

Uses the global `stop_loss_pct` config value (default 2%).

```
stop_loss_price = entry_price * (1 - stop_loss_pct)
```

The monitor closes the position with `exit_reason = STOP_LOSS` if
`current_price <= stop_loss_price`.

---

## Exit Conditions

| Condition | Trigger | Exit reason |
|---|---|---|
| Profit target | `current_price >= exit_target["value"]` | `PROFIT_TARGET` |
| Stop loss | `current_price <= stop_loss_price` | `STOP_LOSS` |
| Window expiry | Session ordinal reaches `evaluation_window_session` | `WINDOW_EXPIRY` |

---

## Evaluation Window

**4 sessions after the position closes.**

`evaluation_window_session = entry_session_ordinal + 4`

The feedback agent evaluates whether the price reverted to SMA_20 within 4 sessions of
the trade. This is a long enough window for reversion to complete without waiting for
multi-day drift.

---

## Feedback Evaluation Criteria

The feedback agent compares:
- **Thesis**: price was extended below SMA_20 and was expected to revert upward
- **Outcome**: did price reach or exceed SMA_20 within the evaluation window?
- **Judgment**:
  - `CORRECT` — position was closed at PROFIT_TARGET or price was near/above SMA_20 at evaluation time
  - `INCORRECT` — position was closed at STOP_LOSS or price remains significantly below SMA_20
  - `NEUTRAL` — position closed at WINDOW_EXPIRY with modest gain/loss (<1%)
