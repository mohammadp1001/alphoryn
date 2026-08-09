# Report Template Context: Alphoryn

Phase 1 output | Date: 2026-07-05 (updated 2026-08-09) | Plan: ../plan.md

Documents the Jinja2 context object passed by `reports/generator.py` to the unified
session report template (`templates/reports/session.html.j2`), as actually built by
`scheduler/scheduler.py::_process_session`.

## Context Object Fields (as built by the scheduler)

session_id: str
candle_close_at: str        -- formatted "2026-07-05 14:00 UTC"
tickers: list[str]          -- all tickers processed this session, e.g. ["SPY", "QQQ"]
ticker_details: list[dict]  -- one entry per ticker, see below
strategy: str|None          -- known gap: currently set from the FIRST ticker's decision only,
                                not per ticker (see Known Gaps)
signals: dict|None          -- known gap: currently always None (never populated) — the
                                Signal Snapshot section of the template never renders
execution_result: str|None  -- known gap: the top-level field is always None. The real
                                per-ticker result lives in ticker_details[].execution_result
position: dict|None         -- known gap: currently always None (never populated) — the
                                Position section always renders "No position opened this session"

## ticker_details dict keys (one per ticker)

ticker: str
action: str           -- "BUY", "SELL", or "HOLD"
strategy: str|None    -- "MEAN_REVERSION" or "MOMENTUM"; None if HOLD with no strategy selected
reasoning: str         -- agent's full reasoning text; IS the investment thesis, rendered per ticker
memory_summary: str|None  -- known gap: currently always None (never populated from the memory bank)
execution_result: str|None -- "EXECUTED", "HOLD" or "FAILED" for this ticker, from
                              ExecutionAgent.execute(); None when execution did not run

## signals dict keys (when populated)

rsi_14, adx_14, ema_20, ema_50, sma_20, bollinger_upper, bollinger_lower,
bollinger_pct_b, macd_line, macd_signal, macd_histogram, volume_vs_avg,
current_price, price_vs_ema_20_pct, price_vs_sma_20_pct

All floats. Matches `AssetSignals` in data-model.md.

## position dict keys (when populated)

entry_price: float
lot_size: int
stop_loss_price: float
exit_target: dict  -- {"type": "price_level", "value": 467.32} or {"type": "trailing_stop", "trail_pct": 0.015}
trailing_stop_high_watermark: float|None  -- Momentum only; None for Mean Reversion

## Template

A single unified template renders the whole session report:
`templates/reports/session.html.j2`. It lists all tickers' decisions in a table (`ticker_details`),
renders one Investment Thesis section per ticker, and renders a single Signal Snapshot and
Position section (see Known Gaps — these are currently always empty in practice since the
scheduler never populates `signals`/`position`).

## Thesis extraction (feedback agent)

The feedback agent parses `section id="investment-thesis-{ticker}"` from the rendered HTML
— the id is ticker-scoped, so a multi-ticker session cannot have one ticker's thesis judged
against another's outcome (issue #134). The `reasoning` field rendered inside is the thesis
for that ticker.

Reports written before that change used one unscoped `investment-thesis` id for every
ticker. They are still reachable from the memory bank, so the agent falls back to the
unscoped id, and then to the whole document, before giving up.

## Known Gaps

The following context fields are wired into the template but never populated by the
scheduler in the current implementation — they are always `None`, so the corresponding
template sections never render real data:
- `strategy` (top-level) — only the first ticker's strategy is passed; not accurate for
  multi-ticker sessions where tickers run different strategies (spec FR-008)
- `signals`, top-level `execution_result`, `position` — always `None`; the Signal Snapshot
  and Position sections of the report never show data even when a trade executed.
  `ticker_details[].execution_result` *is* populated, so the per-ticker decision table does
  show what happened to each order
- `ticker_details[].memory_summary` — always `None`; the memory-context box never renders

These are implementation gaps to track separately, not documentation errors.
