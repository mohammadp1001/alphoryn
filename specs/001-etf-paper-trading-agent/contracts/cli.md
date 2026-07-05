# CLI Contract: Alphoryn

**Phase 1 output** | **Date**: 2026-07-03 | **Plan**: [../plan.md](../plan.md)

Implemented by: `alphoryn/cli/main.py` (Typer)

---

## Command: `alphoryn run`

Start a paper trading session. Config file is the base; CLI options override individual
fields. At least `--etf1` and `--etf2` must be present (via config or CLI).

```
Usage: alphoryn run [OPTIONS]

Options:
  --config    PATH    Path to JSON config file. Default: ./config.json
  --etf1      TEXT    ETF 1 ticker (US-listed, e.g. SPY). Overrides config.
  --etf2      TEXT    ETF 2 ticker (US-listed, e.g. QQQ). Overrides config.
  --exchange  TEXT    Optional/informational. Alpaca routes automatically. Overrides config.
  --timeframe TEXT    Candle timeframe: 30min | 1H | 4H. Overrides config.
  --duration  TEXT    Run duration: e.g. 8H | 24H. Overrides config.
  --budget    FLOAT   Session money budget in USD. Overrides config. 0 = no limit.
  --stop-loss FLOAT   Stop-loss percentage, e.g. 0.02 for 2%. Overrides config.
  --help              Show this message and exit.
```

**Startup output** (to stdout before first candle close):
```
Alphoryn v0.0.1 — Paper Trading
ETFs: SPY / QQQ | Timeframe: 1H | Duration: 24H
Sessions planned: 6
Memory bank: /home/user/.alphoryn/memory.db — 0 open positions loaded
Waiting for next candle close at 2026-07-03 15:00 UTC (12 min 34 sec)
```

**During investigation** (heartbeat, every 5 minutes):
```
[run-1/session-a3f7] investigating... 10 min elapsed
[run-1/session-a3f7] investigating... 15 min elapsed
```

**Session completion**:
```
[run-1/session-a3f7] ETF1: MEAN_REVERSION → BUY (executed)
[run-1/session-a3f7] ETF2: MOMENTUM → HOLD
[run-1/session-a3f7] Report: reports/run-1/session-a3f7.html
```

**Failure / skip**:
```
[run-1/session-b9c2] WARN: investigation timeout — Hold forced on all ETFs
[run-1/session-c1d4] SKIP: market data unavailable — session not counted against total
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

**Output**:
```
Current run: run-1 (started 2026-07-03 14:00 UTC)
Sessions: 3 completed, 3 remaining

Open positions:
  ETF1 SPY  MEAN_REVERSION  BUY @ 540.12  Stop: 529.32  Status: OPEN
  ETF2 QQQ  (no open position)
```

---

## Command: `alphoryn history`

Show session history and feedback evaluations from the memory bank.

```
Usage: alphoryn history [OPTIONS]

Options:
  --run INT    Filter by run number. Default: latest run.
  --db PATH    Memory bank path. Default: ~/.alphoryn/memory.db
  --help
```

**Output** (table, most recent first):
```
Session              Candle Close          ETF1                ETF2
run-1/session-a3f7   2026-07-03 14:00     MR → BUY (exec)     MOM → HOLD
run-1/session-b9c2   2026-07-03 15:00     MOM → HOLD          MOM → SELL (exec)
...
```

