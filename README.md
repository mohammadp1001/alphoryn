# alphoryn

Autonomous ETF paper trading agent. Uses Google ADK + Gemini to analyse market signals for two ETFs (SPY/QQQ) and execute paper trades via Alpaca. Secrets live in Google Secret Manager; positions and session history are stored in a local SQLite memory bank.

---

## Quickstart

### Prerequisites

- Python 3.13+
- Free [Alpaca paper trading account](https://alpaca.markets) (no deposit required)
- Google Cloud project with Secret Manager API enabled
- `gcloud` CLI authenticated: `gcloud auth application-default login`

### 1. Install

```bash
git clone <repo-url> alphoryn
cd alphoryn
pip install -e ".[dev]"
```

Verify:

```bash
alphoryn --help
```

### 2. Store Alpaca credentials in Google Secret Manager

```bash
echo -n "YOUR_ALPACA_API_KEY"    | gcloud secrets create alphoryn-alpaca-api-key    --data-file=-
echo -n "YOUR_ALPACA_SECRET_KEY" | gcloud secrets create alphoryn-alpaca-secret-key --data-file=-
```

### 3. Create a config file

```bash
cp config.json.example config.json
```

Minimum required fields:

```json
{
  "etf1": "SPY",
  "etf2": "QQQ"
}
```

See `specs/001-etf-paper-trading-agent/contracts/config-schema.md` for all fields and defaults.

### 4. Run

```bash
# Use config.json in the current directory
alphoryn run

# Override fields at the command line
alphoryn run --etf1 SPY --etf2 QQQ --duration 8H --stop-loss 0.02

# Point to a different config file
alphoryn run --config /path/to/my-config.json
```

The agent will:

1. Fetch Alpaca credentials from Google Secret Manager
2. Load open positions from the local memory bank (`~/.alphoryn/memory.db`)
3. Wait for the next candle close, then begin the investigate → decide → execute loop

### 5. Monitor

```bash
# From a second terminal while a run is active
alphoryn status

# View session history
alphoryn history
alphoryn history --run 1
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| Exit code 1 | Invalid or missing config | Check `config.json` has `etf1` and `etf2` |
| Exit code 2: memory bank inaccessible | `~/.alphoryn/memory.db` corrupt | Delete the file and restart (positions lost) |
| Exit code 3: Secret Manager unreachable | GCP credentials not set | Run `gcloud auth application-default login` |
| `APIError: 403` | Invalid Alpaca API key | Regenerate key at alpaca.markets and update GCP secrets |
| `etf1 == etf2` validation error | Duplicate ticker | Set different tickers in config |
