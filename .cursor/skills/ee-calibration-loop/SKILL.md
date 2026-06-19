---
name: ee-calibration-loop
description: Iterates entity extraction and llm-as-judge-EE evaluation until quantitative convergence thresholds are met or progress stalls. Runs process, measures markup error rates, optimizes scoped prompts, and logs each iteration to the benchmark DB. Use when calibrating EE prompts, auto-tuning extraction for a document/model/domain, or when the user asks for convergence, calibration loop, or iterative prompt improvement.
---

# EE Calibration Loop

Wrapper around [llm-as-judge-ee](../llm-as-judge-ee/SKILL.md). Repeatedly **extract → measure → judge → optimize prompts** until convergence or a safety limit.

## Prerequisites

- `uv sync --extra benchmark`
- LLM available for extraction
- User confirms loop start once (auto-optimizes prompts each iteration — no per-iteration AskQuestion)

## Inputs

| Input | Example |
|-------|---------|
| Source document | `input/ZDU_prereqs.txt` |
| Domain | `technical` |
| Model | from `config.yaml` (resolved at runtime) |
| Markup output | `data/documents/{stem}_markup.html` |
| Thresholds | `.cursor/skills/ee-calibration-loop/thresholds-technical.json` |
| Max iterations | default `5` |

## Convergence indicators

Use **all hard gates** plus **plateau detection**. Details: [convergence-indicators.md](convergence-indicators.md).

### Hard gates (all must pass)

| Indicator | Formula | Default threshold | What it catches |
|-----------|---------|-------------------|-----------------|
| `orphan_rate` | orphans / unique entities | ≤ 10% | Markup/linking gaps, canonical-form mismatch |
| `verbatim_rate` | verbatim_issues / unique entities | ≤ 5% | Paraphrase, casing drift, invented spans |
| `other_rate` | `Other` count / unique entities | ≤ 10% | Weak type disambiguation |
| `generic_hit_rate` | blocklist hits / unique entities | ≤ 3% | Low-value operational phrase extraction |
| `error_score` | weighted composite (see below) | ≤ 0.12 | Overall noise floor |
| `grade_score` | from judge letter grade | ≥ 85 (B+) | Qualitative guardrail |

**Composite error score** (minimize):

```
error_score = 0.30×orphan_rate + 0.30×verbatim_rate + 0.20×other_rate + 0.20×generic_hit_rate
```

### Stop conditions (without convergence)

| Condition | Default | Action |
|-----------|---------|--------|
| `max_iterations` | 5 | Stop; report best iteration |
| `stalled` | error_score Δ < 0.02 vs previous | Stop; likely prompt ceiling or pipeline issue |
| User abort | — | Stop immediately |

### Do not use as primary convergence signals

- **Entity count** — dropping entities may mean over-pruning, not quality
- **Marked span count** — repetition inflates; says nothing about precision
- **Benchmark entity yield** — optimizes quantity, not correctness
- **`orphan_rate` alone** — high orphans may be resolver/markup, not fixable by prompts

## Workflow

```
Task Progress:
- [ ] 1. Confirm source, domain, model, max_iterations, thresholds file
- [ ] 2. Ask user once: start calibration loop? (warn: overwrites prompts each iteration)
- [ ] 3. Loop (iteration N):
- [ ]    a. Run extraction
- [ ]    b. Run analyze_markup.py --json
- [ ]    c. Run check_convergence.py
- [ ]    d. Follow llm-as-judge-ee (report + log eval; skip AskQuestion — optimize if not converged)
- [ ]    e. If converged → exit success
- [ ]    f. If stalled or N >= max_iterations → exit with summary
- [ ]    g. Else apply scoped prompt fixes, log prompts_after, continue
- [ ] 4. Print iteration table from benchmark ee_judge_evaluations
```

### Step 3a — Extract

```bash
uv run python main.py process input/{filename} --domain {domain}
```

### Step 3b–c — Measure and check convergence

```bash
METRICS=$(mktemp)
PREV="${PREV_METRICS:-}"

uv run python .cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py \
  data/documents/{stem}_markup.html input/{filename} --json > "$METRICS"

uv run python .cursor/skills/ee-calibration-loop/scripts/check_convergence.py \
  --metrics-file "$METRICS" \
  --markup data/documents/{stem}_markup.html \
  --thresholds-file .cursor/skills/ee-calibration-loop/thresholds-{domain}.json \
  --grade-score {grade_score} \
  ${PREV:+--previous-metrics-file "$PREV"}
```

Save `"$METRICS"` as `PREV_METRICS` for the next iteration. Exit code `0` from `check_convergence.py` means converged.

### Step 3d — Judge and log

Follow **llm-as-judge-ee** steps 3–6. In loop mode:

- **Skip** step 6 AskQuestion — optimize prompts when `converged` is false
- Log each iteration to benchmark (`log_ee_evaluation.py`)
- After prompt edits, log `prompts_after` with the same `eval_id`

### Step 4 — Iteration summary

```bash
uv run python main.py benchmark query "
  SELECT strftime(recorded_at, '%H:%M') AS t, grade, grade_score,
         orphan_rate, verbatim_issues, optimization_applied, left(summary, 50)
  FROM ee_judge_evaluations
  WHERE document_filename = '{filename}'
  ORDER BY recorded_at DESC
  LIMIT 10"
```

## Tuning thresholds

Copy `thresholds-technical.json` per domain. Relax `max_orphan_rate` if orphans persist after prompt fixes (likely pipeline/resolver — stop loop and fix markup linking instead).

Literary/scientific domains: raise `max_other_rate` or disable `generic_hit_rate` gate (empty blocklist) via domain-specific thresholds file.

## Related skills

- Evaluation detail: [llm-as-judge-ee](../llm-as-judge-ee/SKILL.md)
- Indicator rationale: [convergence-indicators.md](convergence-indicators.md)
