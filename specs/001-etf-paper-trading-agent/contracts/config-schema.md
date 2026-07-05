# Config Schema: Alphoryn

**Phase 1 output** | **Date**: 2026-07-03 | **Plan**: [../plan.md](../plan.md)

Implemented by: `alphoryn/config/models.py` (Pydantic)

---

## JSON Config File (`config.json`)

All fields optional except where noted. CLI arguments override any field.
No secrets belong in this file — credentials are fetched from Google Secret Manager.

```json
{
  "etf1": "SPY",
  "etf2": "QQQ",
  "candle_timeframe": "1H",
  "run_duration": "24H",
  "session_money_budget": 1000.0,
  "stop_loss_pct": 0.02,
  "max_startup_latency_seconds": 60,
  "currency": "USD",
  "memory_db_path": "~/.alphoryn/memory.db"
}
```

## Field Reference

| Field | Required | Type | Allowed Values | Notes |
|---|---|---|---|---|
| `etf1` | Yes | string | Any valid ticker | Exchange suffix auto-applied from `exchange` if absent |
| `etf2` | Yes | string | Any valid ticker | Must differ from `etf1` |
| `candle_timeframe` | No | string | `"30min"`, `"1H"`, `"4H"` | Default: `"1H"` |
| `run_duration` | No | string | `"NHM"` format, e.g. `"24H"`, `"8H"` | Default: `"24H"` |
| `exchange` | No | string | `"NYSE"`, `"NASDAQ"`, `"AMEX"` | Informational only; Alpaca routes automatically. Market hours from Alpaca calendar API. Default: omitted (auto-detected from ticker). |
| `session_money_budget` | No | float or null | Positive USD amount | `null` = no budget limit |
| `stop_loss_pct` | No | float | `0.001`–`0.20` | Default: `0.02` (2%). Applied as hard config value at trade entry. |
| `max_startup_latency_seconds` | No | integer | `10`–`300` | Default: `60`. System warns if exceeded; never blocks. |
| `currency` | No | string | `"USD"` | Default: `"USD"`. Only USD supported in v0.0.1 (Alpaca paper accounts are USD). |
| `memory_db_path` | No | string | Valid filesystem path | Default: `~/.alphoryn/memory.db` |

## Validation Rules

- `etf1` ≠ `etf2` (enforced by Pydantic validator)
- `run_duration` must be evenly divisible by `candle_timeframe` — if not, system warns and
  rounds down at startup (spec FR-003); this is a warning, not a config error
- `stop_loss_pct` must be in range `(0, 1)` exclusive
- `session_money_budget`, if set, must be > 0

## Google Secret Manager Secrets

These are NOT in the config file. They are fetched at startup by `secrets/client.py` and
injected as environment variables (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`) before the
Alpaca MCP server connection is established.

| Secret name (GCP) | Env var injected | Required |
|---|---|---|
| `alphoryn-alpaca-api-key` | `ALPACA_API_KEY` | Yes |
| `alphoryn-alpaca-secret-key` | `ALPACA_SECRET_KEY` | Yes |

Alpaca keys are obtained from alpaca.markets (free paper trading account).
MCP server runs in paper trading mode by default (`ALPACA_PAPER_TRADE=true`).

GCP credentials: Application Default Credentials (`gcloud auth application-default login`
or set `GOOGLE_APPLICATION_CREDENTIALS`). No additional secret needed for Secret Manager itself.
