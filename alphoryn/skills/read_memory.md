# Skill: Read Memory

**Used by**: main_agent at the start of investigation, before regime identification.
**Input**: ETF ticker and candidate strategy (determined after regime identification — run
this skill again once regime is declared if memory context is needed per-strategy).
**Output**: Memory summary string + adjustment flag for entry skills.

---

## Instructions

### Step 1 — Query recent MemoryEntry records

Look up the last 5 `MemoryEntry` records for this ETF + strategy combination, ordered
by `created_at` descending. These are available in the memory context passed to the agent
at session start.

Fields to examine per record:
- `decision` — BUY, SELL, or HOLD
- `outcome_judgment` — CORRECT, INCORRECT, NEUTRAL, or NULL (not yet evaluated)
- `regime_context` — JSON summary of market conditions at entry

### Step 2 — Count outcomes

From records where `outcome_judgment` is not NULL:

```
correct_count  = count where outcome_judgment == "CORRECT"
incorrect_count = count where outcome_judgment == "INCORRECT"
total_evaluated = correct_count + incorrect_count  (exclude NEUTRAL and NULL)
```

If `total_evaluated == 0`: no adjustment needed, proceed normally.

### Step 3 — Check INCORRECT rate

```
incorrect_rate = incorrect_count / total_evaluated
```

If `incorrect_rate > 0.60` (more than 60% of recent evaluated trades were wrong):
- Set `memory_adjustment = True`
- This will be passed to the entry skill — it requires stronger signal (4+ conditions)

Otherwise: `memory_adjustment = False`

### Step 4 — Compose memory summary

Write a 1–2 sentence summary to include in your reasoning:

- If `total_evaluated == 0`:
  `"No prior {strategy} trades for {etf} to reference."`
- If `memory_adjustment`:
  `"Recent {strategy} performance on {etf}: {incorrect_count}/{total_evaluated} incorrect — requiring stronger entry signal."`
- Otherwise:
  `"Recent {strategy} performance on {etf}: {correct_count}/{total_evaluated} correct."`

### Step 5 — State in reasoning

Include the memory summary in your reasoning before proceeding to regime identification.
It frames the decision context and is captured in the HTML report as part of the thesis.

### Example reasoning format

```
Memory: SPY MEAN_REVERSION — last 5 evaluated trades
  CORRECT: 3, INCORRECT: 1, NEUTRAL: 1, NULL: 0
  incorrect_rate = 1/4 = 25% → no adjustment
  Summary: "Recent MEAN_REVERSION performance on SPY: 3/4 correct."
```

```
Memory: QQQ MOMENTUM — last 5 evaluated trades
  CORRECT: 1, INCORRECT: 3, NEUTRAL: 0, NULL: 1
  incorrect_rate = 3/4 = 75% → memory_adjustment = True
  Summary: "Recent MOMENTUM performance on QQQ: 3/4 incorrect — requiring stronger entry signal."
```

---

## Output

Pass `memory_adjustment` (bool) and `memory_summary` (str) to the entry skill.
Include `memory_summary` in the final reasoning field of the ETFDecision.
