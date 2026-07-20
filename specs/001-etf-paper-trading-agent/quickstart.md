# Quickstart: Alphoryn v0.0.1

**Phase 1 output** | **Date**: 2026-07-03 | **Plan**: [plan.md](plan.md)

---

## Prerequisites

- Python 3.13+
- Free Alpaca paper trading account at [alpaca.markets](https://alpaca.markets) (no deposit required)
- Google Cloud project with Secret Manager API enabled
- `gcloud` CLI authenticated (`gcloud auth application-default login`)

---

## 1. Install

```bash
git clone <repo-url> alphoryn
cd alphoryn
pip install -e ".[dev]"
```

Verify:
```bash
alphoryn --help
ruff check .
pytest --cov=alphoryn
```

---

## 2. Get Alpaca paper trading API keys

1. Sign up at [alpaca.markets](https://alpaca.markets) → create a paper trading account
2. Dashboard → Paper Trading → API Keys → Generate New Key
3. Copy the **API Key ID** and **Secret Key** (shown once)

---

## 3. Store Alpaca credentials in Google Secret Manager

```bash
echo -n "YOUR_ALPACA_API_KEY"    | gcloud secrets create alphoryn-alpaca-api-key    --data-file=-
echo -n "YOUR_ALPACA_SECRET_KEY" | gcloud secrets create alphoryn-alpaca-secret-key --data-file=-
```

---

## 4. Create your config file

```bash
cp config.json.example config.json
```

Minimum required fields — at least 2 US-listed tickers:

```json
{
  "tickers": ["SPY", "QQQ"]
}
```

See `contracts/config-schema.md` for all fields and defaults.
Note: tickers must be US-listed (NYSE/NASDAQ/AMEX) — Alpaca covers US equities only.

---

## 5. Run

```bash
# Use config.json in current directory
alphoryn run

# Override individual fields
alphoryn run --tickers SPY,QQQ --duration 8H --stop-loss 0.02

# Use a different config file
alphoryn run --config /path/to/my-config.json
```

The system will:
1. Fetch Alpaca credentials from Google Secret Manager and connect to Alpaca paper account
2. Validate config and load open positions from the local memory bank
3. Display the planned session count and time until next candle close (NYSE hours)
4. Wait for the next candle boundary, then begin the investigate-decide-execute loop

---

## 6. Monitor status

```bash
# While a run is active (from another terminal)
alphoryn status

# View session history
alphoryn history
alphoryn history --run 1
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| Exit code 2: memory bank inaccessible | `~/.alphoryn/memory.db` missing or corrupt | Delete and restart (positions lost) or restore from backup |
| Exit code 3: Secret Manager unreachable | GCP credentials not set | Run `gcloud auth application-default login` |
| `alpaca.common.exceptions.APIError: 403` | Invalid or expired Alpaca API key | Regenerate key at alpaca.markets and update GCP secrets |
| `alpaca.common.exceptions.APIError: 422` | Invalid ticker symbol | Confirm ticker is US-listed and correct |
| `tickers must contain at least 2 symbols` validation error | Fewer than 2 tickers in config | Provide at least 2 tickers |
| Fractional session warning at startup | `run_duration` not evenly divisible by `candle_timeframe` | Adjust either field; system rounds down and proceeds |
