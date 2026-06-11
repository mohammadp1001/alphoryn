# Engineering Memo — alphoryn

**To:** Reviewing engineer  
**From:** Mohammad  
**Date:** 2026-06-11

---

## What was built

An autonomous ETF trading agent running on Google ADK. A coordinator orchestrates four
sub-agents in sequence: **research** (market regime, macro data, news, earnings calendar),
**analysis** (technical and momentum scoring, ETF screening), **risk debate** (optimist vs.
pessimist verdict), and **execution** (paper trade on Alpaca).

Every tool function returns a Pydantic-validated model via `.model_dump()`. Every agent
enforces `output_schema` so silent empty returns abort the cycle rather than silently
corrupting downstream state. Structured I/O is logged at every agent boundary via ADK
callbacks. A SQLite database tracks sessions, trade records, pairwise win/loss counts per
agent, and regime statistics. The CLI (`algotrade run`) supports SEMI_AUTO and FULL_AUTO
modes with a configurable loss limit, universe, and HITL timeout. CI enforces 100% unit
test coverage and zero Ruff violations on every PR.

---

## What was cut

- **Outcome resolution webhook.** `infra/webhook.py` exists but is not deployed. Alpaca
  fills are not yet fed back to the pairwise calibration table. Win/loss attribution is
  therefore absent; the risk synthesis uses equal 0.5/0.5 agent weights until the first
  resolved cycle.
- **Eval harness fixtures.** `evals/scenarios/` is scaffolded but empty. No recorded
  session has been replayed against the grader. Prompt quality is validated by prompt-string
  unit tests, not end-to-end eval.
- **German market sector map.** The `GERMAN_MARKET` universe works but `sector` returns
  `"Unknown"` for most holdings because yfinance does not carry German ETF metadata.
  A curated static map was scoped but not written.
- **Rate limiter coverage.** `infra/rate_limiter.py` is wired into agent callbacks but not
  uniformly applied to every yfinance call. High-frequency screening runs can still burst.

---

## What additional time would have addressed

1. **Close the calibration loop.** Deploy the webhook, wire Alpaca fill events to
   `db.schema.resolve_trade`, and let the pairwise win rates drift away from 0.5 after the
   first dozen live cycles. The debate model is designed for this signal; without it the
   optimist and pessimist carry equal weight unconditionally.
2. **Eval harness.** Record two or three live sessions with `evals/record_scenario.py`,
   build rubric criteria for regime classification accuracy and risk-level appropriateness,
   and run `agents-cli eval grade` in CI. Right now the only gate on agent behaviour is
   human review of run logs.
3. **Vertex AI quota management.** The pipeline hit 429 RESOURCE_EXHAUSTED in testing.
   AI Studio API key fallback, per-model token budgets, and a dead-letter queue for
   interrupted sessions would make the system production-viable.

---

## Design decision I would defend

**Debate agents using two different reasoning models with long-term pairwise memory,
over a single risk-scoring function.**

The obvious alternative is a deterministic risk scorer: compute volatility, momentum, and
regime fit, weight them, threshold on a number. It is fast, auditable, and reproducible.
The reason I did not choose it is that the signal it would suppress is the one that matters
most in a regime transition — the qualitative disagreement between a bull thesis and a
bear thesis for the same asset at the same moment.

Two agents with different model providers (OpenRouter optimist vs. pessimist) are exposed
to different pre-training distributions. They do not share the same inductive biases about
what constitutes a credible risk argument. When they agree, confidence is higher. When they
diverge sharply — debate tie within `DEBATE_TIE_THRESHOLD_PCT` — the coordinator surfaces
the trade for human review regardless of operating mode. That is behaviour a weighted
scalar cannot produce.

The long-term pairwise memory exists to make this honest over time. After enough resolved
trades, the agent whose verdicts correlated with profitable outcomes earns a higher weight
in risk synthesis. An agent that is systematically overconfident loses influence without
being removed. The calibration decays gracefully: a fresh install starts at 0.5/0.5 and
converges as evidence accumulates. This is a bet that the value of structured disagreement
compounds — that the system gets better at knowing which agent to trust in which regime,
rather than requiring a human to retune a scoring function every quarter.
