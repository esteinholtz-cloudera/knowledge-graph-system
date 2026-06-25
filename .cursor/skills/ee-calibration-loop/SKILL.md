---
name: ee-calibration-loop
description: Iterates entity extraction and llm-as-judge-EE evaluation until quantitative convergence thresholds are met or progress stalls. Runs process, measures markup error rates, optimizes scoped prompts, and logs each iteration to the benchmark DB. Use when calibrating EE prompts, auto-tuning extraction for a document/model/domain, or when the user asks for convergence, calibration loop, or iterative prompt improvement.
frontmatter: Iterates entity extraction and llm-as-judge-EE evaluation until quantitative convergence
---

# EE Calibration Loop

Wrapper around [llm-as-judge-ee](../llm-as-judge-ee/SKILL.md). Repeatedly **extract → measure → judge → optimize prompts** until convergence or a safety limit.

## Prerequisites

- `uv sync --extra benchmark`
- LLM available for extraction
- User confirms loop start once (auto-optimizes prompts each iteration — no per-iteration AskQuestion)

## Inputs


| Input           | Example                                                        |
| --------------- | -------------------------------------------------------------- |
| Source document | `input/ZDU_prereqs.txt`                                        |
| Domain          | `technical`                                                    |
| Model           | from `config.yaml` (resolved at runtime)                       |
| Markup output   | `data/documents/{stem}_markup.html`                            |
| Thresholds      | `.cursor/skills/ee-calibration-loop/thresholds-technical.json` |
| Max iterations  | default `5`                                                    |


## Convergence indicators

Use **all hard gates** plus **plateau detection**. Details: [convergence-indicators.md](convergence-indicators.md).

### Hard gates (all must pass)


| Indicator          | Formula                           | Default threshold | What it catches                              |
| ------------------ | --------------------------------- | ----------------- | -------------------------------------------- |
| `orphan_rate`      | orphans / unique entities         | ≤ 10%             | Markup/linking gaps, canonical-form mismatch |
| `verbatim_rate`    | verbatim_issues / unique entities | ≤ 5%              | Paraphrase, casing drift, invented spans     |
| `other_rate`       | `Other` count / unique entities   | ≤ 10%             | Weak type disambiguation                     |
| `generic_hit_rate` | blocklist hits / unique entities  | ≤ 3%              | Low-value operational phrase extraction      |
| `error_score`      | weighted composite (see below)    | ≤ 0.12            | Overall noise floor                          |
| `grade_score`      | from judge letter grade           | ≥ 85 (B+)         | Qualitative guardrail                        |


**Composite error score** (minimize):

```
error_score = 0.30×orphan_rate + 0.30×verbatim_rate + 0.20×other_rate + 0.20×generic_hit_rate
```

### Stop conditions (without convergence)


| Condition        | Default                          | Action                                        |
| ---------------- | -------------------------------- | --------------------------------------------- |
| `max_iterations` | 5                                | Stop; report best iteration                   |
| `stalled`        | error_score Δ < 0.02 vs previous | Stop; likely prompt ceiling or pipeline issue |
| User abort       | —                                | Stop immediately                              |


### Do not use as primary convergence signals

- **Entity count alone** — dropping entities may mean over-pruning *or* yield collapse from prompt/chunk budget; check `empty_chunk_rate` and per-chunk yield first
- **Marked span count** — repetition inflates; says nothing about precision
- **Benchmark entity yield** — optimizes quantity, not correctness
- **`orphan_rate` alone** — high orphans may be resolver/markup, not fixable by prompts

### Prompt/chunk budget guardrails

Treat `prompt_words + chunk_size` as **context for reporting**, not a calibrated cliff. The operative health signals are per-chunk yield from the benchmark DB:

| Signal | Source | Regression trigger |
|--------|--------|-------------------|
| `empty_chunk_rate` | `chunks.entities` per run | ≥ 10% or spike vs prior iteration |
| `entities_raw` | `runs` table | drops ≥ 15% vs prior iteration after prompt growth |
| `mean_entities_per_chunk` | derived | collapses with high empty-chunk rate |

After each extraction (step 3a), report budget + yield:

```bash
uv run python scripts/chunk_yield.py \
  --document {filename} \
  --model {model} \
  --prompts-dir prompts/{model}/{domain} \
  ${PREV_RUN_ID:+--previous-run-id "$PREV_RUN_ID"}
```

Save `run_id` as `PREV_RUN_ID` for the next iteration.

**If yield regresses** after growing the prompt: run one controlled diagnostic (same prompt, smaller chunk) before attributing cause:

```bash
uv run python scripts/run_chunk_diagnostic.py \
  --source input/{filename} \
  --domain {domain} \
  --model {model} \
  --baseline-run-id {prior_run_id}
```

- `attribution: budget_dilution` → shrink `chunk_size` or trim prompt before adding rules
- `attribution: prompt_content` → revert/soften restrictive phrasing (`Extract only…`, heavy `Do not…` lists)

**Optional validation** (once per model+domain, fixed prompt): controlled chunk sweep to quantify soft budget effect:

```bash
uv run python scripts/validate_chunk_budget.py \
  --source input/{filename} \
  --chunk-sizes 200 300 400
```

Results: `data/chunk_budget_validation.json`. Expect weak/non-monotonic effects at ~130w prompts — use as evidence, not a magic threshold.

## Workflow

```
Task Progress:
- [ ] 0. (Optional) Benchmark chunking strategies on source doc
- [ ] 1. Confirm source, domain, model, max_iterations, thresholds file
- [ ] 2. Ask user once: start calibration loop? (warn: overwrites prompts each iteration)
- [ ] 3. Loop (iteration N):
- [ ]    a. Run extraction
- [ ]    a2. Report chunk yield + budget (`scripts/chunk_yield.py`); if regressed → diagnostic
- [ ]    b. Run analyze_markup.py --json
- [ ]    c. Run check_convergence.py
- [ ]    d. Follow llm-as-judge-ee (report + log eval; skip AskQuestion — optimize if not converged)
- [ ]    e. If converged → exit success
- [ ]    f. If stalled or N >= max_iterations → exit with summary
- [ ]    g. Else apply scoped prompt fixes, log prompts_after, continue
- [ ] 4. Print iteration table from benchmark ee_judge_evaluations
```

### Step 0 — Chunking benchmark (optional)

Compare `fixed` vs `recursive` strategies before prompt tuning:

```bash
# Structural only (instant)
uv run python scripts/benchmark_chunking.py --source input/{filename}

# Full extraction per strategy (slow)
uv run python scripts/benchmark_chunking.py --source input/{filename} --extract --max-chunks 4
```

Default pipeline chunking is **recursive** (paragraph → sentence pack, overlap at sentence boundaries). Legacy **fixed** word window remains available via `chunk_strategy: fixed` in config.

### Step 3a — Extract

```bash
uv run python main.py process input/{filename} --domain {domain}
```

### Step 3a2 — Yield and budget report

```bash
YIELD=$(mktemp)
uv run python scripts/chunk_yield.py \
  --document {filename} \
  --model {model} \
  --prompts-dir prompts/{model}/{domain} \
  ${PREV_RUN_ID:+--previous-run-id "$PREV_RUN_ID"} > "$YIELD"
cat "$YIELD"
```

If `"regressed": true`, run `scripts/run_chunk_diagnostic.py` before prompt optimization. Do not add rules until cause is identified.

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

