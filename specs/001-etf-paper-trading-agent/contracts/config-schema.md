# Config Schema: Alphoryn

**Phase 1 output** | **Date**: 2026-07-03 | **Plan**: [../plan.md](../plan.md)

Implemented by: `alphoryn/config/models.py` (Pydantic)

---

## JSON Config File (`config.json`)

All fields optional except where noted. CLI arguments override any field.
No secrets belong in this file — credentials are fetched from Google Secret Manager.

```json
{
  "tickers": ["SPY", "QQQ"],
  "candle_timeframe": "1H",
  "run_duration": "24H",
  "extended_hours": false,
  "session_money_budget": 1000.0,
  "stop_loss_pct": 0.02,
  "currency": "USD",
  "memory_db_path": "~/.alphoryn/memory.db"
}
```

## Field Reference

| Field | Required | Type | Allowed Values | Notes |
|---|---|---|---|---|
| `tickers` | Yes | list of string | Minimum 2 US-listed tickers | Evaluated independently; no cross-ticker correlation logic |
| `candle_timeframe` | No | string | `"10min"`, `"15min"`, `"30min"`, `"1H"`, `"4H"` | Default: `"1H"` |
| `run_duration` | No | string | `"NHM"` format, e.g. `"24H"`, `"8H"` | Default: `"24H"` |
| `extended_hours` | No | boolean | `true`/`false` | Default: `false`. Allows pre/post-market execution; testing affordance. |
| `exchange` | No | string or null | Any string | Optional, informational only — Alpaca routes US equities automatically; market hours from Alpaca calendar API. Default: `null`. |
| `session_money_budget` | No | float or null | Positive USD amount | `null` = no budget limit |
| `stop_loss_pct` | No | float | `(0, 1)` exclusive | Default: `0.02` (2%). Applied as hard config value at trade entry. |
| `currency` | No | string | `"USD"` | Default: `"USD"`. Only USD supported in v0.0.1 (Alpaca paper accounts are USD). |
| `memory_db_path` | No | string | Valid filesystem path | Default: `~/.alphoryn/memory.db` |

## Validation Rules

- `tickers` must contain at least 2 symbols (enforced by Pydantic validator)
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
