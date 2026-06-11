# CLAUDE.md — AlgoTrade Agent (alphoryn)

## Project summary

Autonomous ETF trading agent built with Python + Google ADK. A multi-agent pipeline
coordinates five sub-agents (research → analysis → risk debate → execution) to screen
ETFs, classify market regime, debate risk, and place paper trades on Alpaca.

CLI entry point: `algotrade run --strategy MOMENTUM --mode SEMI_AUTO --loss-limit 500 --universe GERMAN_MARKET`
Always add `2>&1` to see agent logs.

**Active features (all merged to main as of 2026-06-10):**
- All 52 tool functions return Pydantic-validated models via `.model_dump()`
- All 5 sub-agents have `output_schema` + `output_key` (ADK enforced schema)
- All agent prompts explicitly mention Pydantic enforcement
- Structured I/O logging callbacks on all sub-agents (`agent/callbacks.py`)
- Analysis agent returns ALL ranked symbols — coordinator applies `combined_score < 0.3` filter
- `FiniteFloat` type: NaN/Inf → None to prevent Gemini 400 errors
- Sector default `"Unknown"` when yfinance returns `None` (German ETFs)

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent framework | Google ADK (`google-adk >= 1.0`) |
| LLM | Gemini 2.5 Flash (all sub-agents) |
| Paper trading | Alpaca (`alpaca-py >= 0.28`) |
| Market data | yfinance + Alpaca Data API |
| Memory / calibration | SQLite (local, via `db/schema.py`) |
| Secrets | GCP Secret Manager (Alpaca keys only) |
| Observability | Cloud Trace + Cloud Logging (OpenTelemetry) |
| CLI | Typer + Rich |
| Validation | Pydantic v2 |
| Python | >= 3.11 |

---

## Repo structure

```
agent/          coordinator, research, analysis, risk, execution agents + prompts + callbacks
tools/          6 namespaces: market, analysis, research, execution, memory, coordinator
  schemas.py    ALL Pydantic I/O models (tool models + agent output models at bottom)
  registry.py   Central tool registry — agents receive filtered slices
infra/          rate_limiter, retry, secrets, observability
db/             SQLite schema (sessions, trades, agent_pairwise, regime_stats)
models/         Domain models (PlanState, RiskAssessment, etc.)
cli/            Typer CLI entry point
evals/          Eval harness + scenario YAML fixtures
tests/          unit/ + integration/ — pytest
config.py       DEFAULT_ETF_UNIVERSE, DEBATE_TIE_THRESHOLD_PCT, etc.
```

---

## Agent output models (in `tools/schemas.py`)

```
MarketRegimeOutput   → research_agent   → state key: "market_regime"
RankedSignalsOutput  → analysis_agent   → state key: "ranked_signals"
RiskVerdictOutput    → risk_optimist     → state key: "optimist_verdict"
RiskVerdictOutput    → risk_pessimist    → state key: "pessimist_verdict"
OrderResultOutput    → execution_agent  → state key: "order_result"
```

---

## Code style & conventions

- **Branching policy:** create a new branch for every change — never commit directly to `main`
- **Tool returns:** always `ModelClass(...).model_dump()` — never raw dicts
- **Floats from external APIs:** use `FiniteFloat` to guard against NaN/Inf
- **No logging of secrets:** credentials must never appear in logs (ADR 0002)
- **`terraform.tfvars` is git-ignored** — never commit it
- **Linting:** Ruff (target py311, line-length 100); mypy strict
- **Tests:** pytest; no assertions on LLM output content — use eval harness for that
- **Comments:** only when WHY is non-obvious; no docstring blocks on simple functions

---

## ADK-specific gotchas

- **`output_schema` + tools is unsupported in some ADK versions.** If an agent has both, ADK may raise a validation error. Risk agents (`risk_optimist`, `risk_pessimist`) have `tools=[]` for this reason.
- **Callbacks must use `callback_context` as the parameter name** (keyword arg from ADK). Using any other name (`ctx`, `context`, etc.) raises `TypeError: got an unexpected keyword argument 'callback_context'`.
- **`before_agent_callback` / `after_agent_callback`** are the correct kwarg names on `Agent(...)`. After callbacks can read `callback_context.state[output_key]` to log structured output.
- **`output_schema` prevents silent empty returns.** Without it, agents can return `''` which aborts the cycle silently.

---

## Security constraints (immutable)

- Single GCP service account only (ADR 0002)
- Alpaca credentials injected as env vars into execution agent context only — never logged, stored on PlanState, or passed to other agents
- `terraform.tfvars` is git-ignored — never commit it
- Alpaca credentials only in GCP Secret Manager, never in source control
- `tools/execution/tools.py`: credentials must never be logged

---

## Known bugs / open issues

- **`output_schema` + `tools` ADK conflict** — research and analysis agents both have tools AND `output_schema`. If ADK raises a schema-tools conflict error on a future ADK upgrade, split the tool-calling pass into a separate sub-agent that deposits results in state, then have the schema-constrained agent read state only.
- **`callback_context.user_content`** may be `None` on some ADK invocations (e.g. when called as an `AgentTool` rather than a root agent). The `before_callback` in `callbacks.py` already guards this with a try/except.
- **Pairwise calibration cold start** — fresh installs have no calibration data; risk synthesis uses equal 0.5/0.5 weights. Not a bug, but first few trades have no calibration signal.

---

## Next TODOs (as of last session)

1. **Run `algotrade run ... 2>&1`** to verify callbacks now show structured research/analysis agent JSON logs after the `callback_context` rename fix.
2. **Outcome resolution webhook** — Cloud Run endpoint (`infra/webhook.py`) exists; needs GCP deployment and Alpaca webhook registration.
3. **Eval harness scenarios** — `evals/scenarios/` is stubbed; no real fixture files yet. Record a live session with `evals/record_scenario.py` to create first scenario.
4. **German market universe** — `GERMAN_MARKET` universe uses EWG as benchmark (correct per prompt), but sector ETFs for German market may return `sector="Unknown"` from yfinance. Consider adding a curated sector map for German ETFs.
5. **Rate limiter** — `infra/rate_limiter.py` exists but isn't wired into all yfinance calls uniformly; verify integration test coverage.

---

## Test coverage notes

Tests in `tests/unit/` cover:
- Risk synthesis math (`test_risk_synthesis.py`)
- Rate limiter token bucket (`test_rate_limiter.py`)
- Agent factory construction (`test_agent_factories.py`)
- Prompt content (`test_agent_prompts.py`) — checks `output_schema`-related prompt strings, NOT LLM output
- Tool schemas and DB schema
- CLI, registry, coordinator tools, execution tools, memory tools

Integration tests: `test_regime_detection.py`, `test_loss_limit.py` — require live API keys; skip in CI without env vars.

**Not yet covered:** callbacks behaviour, `after_callback` state reading, full end-to-end cycle with mock ADK session.
