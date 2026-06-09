# ADR 0001 — Deterministic risk synthesis formula

**Status:** Accepted

## Context

After the risk debate, the coordinator must synthesise two agent verdicts (LOW / MEDIUM / HIGH) and their historical win rates into a single `RiskAssessment.level`. The alternative is to let the LLM reason about the synthesis in natural language.

## Decision

The synthesis is computed by a deterministic weighted-vote formula:

```
score = (opt_level × opt_win_rate + pess_level × pess_win_rate)
        / (opt_win_rate + pess_win_rate)
```

where `LOW=0, MEDIUM=1, HIGH=2`. Thresholds: < 0.6 → LOW, 0.6–1.2 → MEDIUM, > 1.2 → HIGH.

Asymmetric override: if `pessimist_win_rate > 0.65` and the pessimist's verdict is HIGH, the level is always HIGH regardless of the weighted score.

The LLM writes `synthesis_reasoning` explaining the outcome; it does not determine `level`.

## Alternatives considered

**LLM-driven synthesis** — the coordinator reasons in natural language from verdicts + win rates and produces a level. Rejected because: (1) the level would vary across runs for identical inputs, breaking reproducibility; (2) the calibration feedback loop depends on `level` being a stable output — if the same inputs produce HIGH one run and MEDIUM the next, the loop teaches nothing.

## Consequences

- `level` is fully reproducible given the same inputs and calibration state
- The asymmetric override encodes explicit loss aversion — losing money is penalised more than missing a gain
- The formula must be unit-tested with known inputs; thresholds may need tuning after live data accumulates
