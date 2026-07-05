# Report Template Context: Alphoryn

Phase 1 output | Date: 2026-07-05 | Plan: ../plan.md

Documents the Jinja2 context object passed by reports/generator.py to each HTML template.

## Context Object Fields

session_id: str
candle_close_at: str  -- formatted "2026-07-05 14:00 UTC"
etf: str              -- ticker e.g. "SPY"
strategy: str         -- "MEAN_REVERSION" or "MOMENTUM"
decision: str         -- "BUY", "SELL", or "HOLD"
reasoning: str        -- agent full reasoning text; IS the investment thesis
signals: dict         -- ETFSignals fields (see below)
execution_result: str|None  -- None if HOLD; else EXECUTED/SKIPPED_BUDGET/SKIPPED_MARKET_CLOSED/SKIPPED_API_ERROR
position: dict|None   -- None if no position opened this session
memory_summary: str|None -- from read_memory skill; None if no prior trades

## signals dict keys

rsi_14, adx_14, ema_20, ema_50, sma_20, bollinger_upper, bollinger_lower,
bollinger_pct_b, macd_line, macd_signal, macd_histogram, volume_vs_avg,
current_price, price_vs_ema_20_pct, price_vs_sma_20_pct

All floats. All fields present for both strategies.

## position dict keys (when not None)

entry_price: float
lot_size: int
stop_loss_price: float
exit_target: dict  -- {"type": "price_level", "value": 467.32} or {"type": "trailing_stop", "trail_pct": 0.015}
trailing_stop_high_watermark: float|None  -- Momentum only; None for Mean Reversion

## Template selection

TEMPLATE_MAP = {"MEAN_REVERSION": "mean_reversion.html.j2", "MOMENTUM": "momentum.html.j2"}

## Thesis extraction (feedback agent)

The feedback agent parses section id="investment-thesis" from the rendered HTML.
Both templates guarantee this element exists for all decisions (BUY/SELL/HOLD).
The reasoning field rendered inside that section is the thesis.
