# CLI Contract: Alphoryn

**Phase 1 output** | **Date**: 2026-07-03 (updated 2026-07-21) | **Plan**: [../plan.md](../plan.md)

Implemented by: `alphoryn/cli/main.py` (Typer)

---

## Command: `alphoryn run`

Start a paper trading session. Config file is the base; CLI options override individual
fields. At least `--tickers` (2 or more, comma-separated) must be present, via config or CLI.

```
Usage: alphoryn run [OPTIONS]

Options:
  --config    PATH    Path to JSON config file. Default: ./config.json
  --tickers   TEXT    Comma-separated ticker symbols, e.g. SPY,QQQ. Overrides config.
  --exchange  TEXT    Optional/informational. Alpaca routes automatically. Overrides config.
  --timeframe TEXT    Candle timeframe: 30min | 1H | 4H. Overrides config.
  --duration  TEXT    Run duration: e.g. 8H | 24H. Overrides config.
  --budget    FLOAT   Session money budget in USD. Overrides config. 0 or negative = no limit.
  --stop-loss FLOAT   Stop-loss percentage, e.g. 0.02 for 2%. Overrides config.
  --help              Show this message and exit.
```

**Known gap**: `extended_hours` and `memory_db_path` are config-only — there is no
`--extended-hours` or `--memory-db-path` CLI override for `run` (unlike `status`/`history`,
which take `--db`).

**Startup output** (to stdout before first candle close):
```
Alphoryn v0.0.1 — Paper Trading
Tickers: SPY, QQQ | Timeframe: 1H | Duration: 24H
Sessions planned: 6
Memory bank: /home/user/.alphoryn/memory.db — 0 open positions loaded
```

**Session completion** (one line per session; ticker decisions are pipe-separated,
not one line per ticker):
```
[run-1/session-a3f7] DECISION  SPY: BUY (MEAN_REVERSION)  |  QQQ: HOLD (MOMENTUM)
[run-1/session-a3f7] Report -> reports/run-1/session-a3f7.html
```

**Failure / skip**:
```
[run-1/session-b9c2] SKIPPED  investigation budget exceeded
[session-c1d4] MARKET_CLOSED — waiting for next candle
```

**Exit codes**:
| Code | Meaning |
|---|---|
| 0 | Run completed normally |
| 1 | Config validation error |
| 2 | Memory bank inaccessible or corrupt (hard abort) |
| 3 | Google Secret Manager unreachable at startup |

---

## Command: `alphoryn status`

Show the current run state and all open positions.

```
Usage: alphoryn status [OPTIONS]

Options:
  --db PATH   Memory bank path. Default: ~/.alphoryn/memory.db
  --help
```

**Output** (one line per ticker configured for the latest run, from its config snapshot):
```
Current run: run-1 (started 2026-07-03 14:00 UTC)
Sessions: 3 completed, 3 remaining

Open positions:
  SPY  MEAN_REVERSION  BUY @ 540.12  Stop: 529.32  Status: OPEN
  QQQ  (no open position)
```

---

## Command: `alphoryn history`

Show session history from the memory bank.

```
Usage: alphoryn history [OPTIONS]

Options:
  --run INT    Filter by run number. Default: latest run.
  --db PATH    Memory bank path. Default: ~/.alphoryn/memory.db
  --help
```

**Output** (table, most recent first; one column per ticker in the run's config snapshot):
```
Session                   Candle Close           SPY                     QQQ
run-1/session-a3f7        2026-07-03 14:00       MR -> BUY (exec)        MOM -> HOLD
run-1/session-b9c2        2026-07-03 15:00       MOM -> HOLD             MOM -> SELL (exec)
...
```
