---
name: llm-as-judge-ee
description: Evaluates entity extraction quality in the knowledge-graph-system pipeline by analyzing markup HTML against source text, computing coverage/precision metrics, logging grade and prompt snapshots to the benchmark DuckDB, classifying failure modes, and optionally optimizing scoped entity prompts after user confirmation. Use when evaluating entity extraction, reviewing *_markup.html output, tuning entity prompts, or assessing EE quality for a model/domain run.
---

# LLM-as-Judge — Entity Extraction (EE)

Evaluate entity extraction runs in this repo. The judge reads **markup HTML + source text + active prompts**, runs quantitative checks, then produces a structured qualitative report with prompt recommendations scoped correctly.

## Inputs

| Input | Typical path |
|-------|--------------|
| Markup HTML | `data/documents/{stem}_markup.html` or `data_save_{model}/documents/{stem}_markup.html` |
| Source text | `input/{filename}` |
| Entity prompts | `prompts/{model}/{domain}/entity.system.txt`, `entity.user.prefix.txt` |
| Domain config | `config/config.yaml` → `domains.{domain}` |
| Model settings | `config/config.yaml` → `llm.model_settings.{model}` |

Resolve `{model}` and `{domain}` from the run metadata, benchmark DB, or user.

## Workflow

```
Task Progress:
- [ ] 1. Locate markup HTML, source text, model, domain
- [ ] 2. Run analyze_markup.py for baseline metrics
- [ ] 3. Read source + markup samples; spot-check failure modes
- [ ] 4. Read active entity prompts and domain config
- [ ] 5. Write evaluation report (template below)
- [ ] 6. Log evaluation to benchmark DB (grade + metrics + prompts_before)
- [ ] 7. Ask user whether to optimize relevant prompts
- [ ] 8. If yes: apply scoped fixes, log prompts_after, suggest re-run extraction
- [ ] 9. Classify each recommendation: generic / domain / model / document
```

### Step 1 — Ground in the pipeline

Before judging, confirm how markup is produced:

- Extraction: `src/extraction/entity_extractor.py` → `PromptStore` or `prompt_builder.py`
- Prompt files: `prompts/{model}/{domain}/` (concrete text, no placeholders)
- Markup: `src/document/html_markup.py` — entity list + in-text spans
- Linking gaps: entities in list but unmarked often indicate resolver/canonical-form mismatch, not just extraction

See `prompts/README.md` and `docs/PROMPT_TUNING.md`.

### Step 2 — Quantitative baseline

```bash
uv run python .cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py \
  data/documents/ZDU_prereqs_markup.html input/ZDU_prereqs.txt

# JSON for downstream comparison
uv run python .cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py \
  data/documents/ZDU_prereqs_markup.html input/ZDU_prereqs.txt --json
```

Key metrics to cite in the report:

| Metric | Meaning |
|--------|---------|
| `unique_entities` | Distinct entities in sidebar list |
| `marked_spans` | In-text highlight count (can exceed unique — repetition is OK) |
| `orphan_rate` | Fraction listed but never marked — extraction vs linking issue |
| `verbatim_issues` | Entities not found verbatim in source |
| `type_distribution_unique` | Overuse of `Other`, misuse of `Event`, etc. |

Manual spot-checks the script does **not** cover:

- Missing entities (recall / coverage gaps)
- Generic-phrase false positives
- Type misclassification with correct span
- Version fragmentation (split product + version spans)
- Truncated or invented composite spans

### Step 3 — Failure mode taxonomy

Classify each issue into one bucket (cite 2–3 examples each):

1. **Generic phrase over-extraction** — operational prose, not linkable names (`restart`, `topic`, `external clients`)
2. **Type misclassification** — wrong type with plausible span (doc titles as `Event`, durations as `Date`)
3. **`Other` overload** — domain types exist in prompt but model defaults to `Other`
4. **Version/config gaps** — missing `replication.factor`, fragmented product+version spans
5. **Span fidelity** — paraphrase, casing drift, truncated titles, invented composites
6. **Redundancy clusters** — abbrev + full form + process variants (`ZDU`, `Zero Downtime Upgrade`, `ZDU process`)
7. **Pipeline/linking** — orphan entities, resolver canonicalization breaking markup match

### Step 4 — Grade and report

Use letter grade with one-line rationale. Rough calibration:

| Grade | Signal |
|-------|--------|
| A | High coverage, >90% precision, types well-distributed, orphans <5% |
| B | Usable; core entities captured; 15–25% noise or moderate gaps |
| C | Major coverage holes or >30% questionable extractions |
| D/F | JSON failures, mass generic extraction, or markup mostly unusable |

### Step 5 — Log to benchmark database

After grading, persist the evaluation to `data/benchmark.duckdb` (`ee_judge_evaluations` table). Requires `uv sync --extra benchmark`.

1. Save metrics JSON from `analyze_markup.py --json` to a temp file.
2. Snapshot **prompts_before** from `prompts/{model}/{domain}/` (entity system + user prefix + suffix).
3. Run the logging script (prints `eval_id` on stdout — save it):

```bash
METRICS=$(mktemp)
uv run python .cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py \
  data/documents/ZDU_prereqs_markup.html input/ZDU_prereqs.txt --json > "$METRICS"

uv run python .cursor/skills/llm-as-judge-ee/scripts/log_ee_evaluation.py \
  --markup data/documents/ZDU_prereqs_markup.html \
  --source input/ZDU_prereqs.txt \
  --model qwen3-30b-a3b-instruct-2507-mlx \
  --domain technical \
  --grade "B-" \
  --summary "Usable but noisy; ~29% orphan entities" \
  --metrics-file "$METRICS" \
  --prompts-dir prompts/qwen3-30b-a3b-instruct-2507-mlx/technical
```

The script auto-links `run_id` from the latest matching `runs` row (same `document_filename` + `llm_model`) when omitted.

**Query logged evaluations:**

```bash
uv run python main.py benchmark query "$(python -c "
from src.storage.benchmark_store import BenchmarkStore
print(BenchmarkStore.EE_JUDGE_SQL)
")"
```

Stored fields: grade, grade_score, summary, quantitative metrics (`metrics_json`), full prompt snapshots (`prompts_before`, `prompts_after`), `optimization_applied`, optional `run_id` FK.

### Step 6 — Ask about prompt optimization

**Stop after logging and the report.** Use AskQuestion before editing any prompt files:

> **Optimize entity extraction prompts for `{model}` / `{domain}` based on this evaluation?**
> - Yes — apply scoped recommendations to `prompts/{model}/{domain}/`
> - No — report only; no prompt changes

If the user declines, do not modify prompts. The benchmark row keeps `prompts_after` NULL and `optimization_applied` FALSE.

If the user accepts:

1. Apply only recommendations scoped to this model/domain (see "Where to patch").
2. Do **not** put document-specific few-shot into shared layers without explicit approval.
3. After edits, log **prompts_after** against the same `eval_id`:

```bash
uv run python .cursor/skills/llm-as-judge-ee/scripts/log_ee_evaluation.py \
  --eval-id "<eval_id from step 5>" \
  --prompts-after-dir prompts/qwen3-30b-a3b-instruct-2507-mlx/technical
```

4. Tell the user to re-run extraction on the same document and optionally re-evaluate to compare grades across benchmark rows.

## Report template

```markdown
## Entity Extraction Evaluation: `{markup_file}`

Analysis of the {model} run against `{source_file}`: **N unique entities**, **M in-text spans**, domain `{domain}`.

### Overall Assessment

**Grade: {grade}** — {one-line summary}

| Metric | Observation |
|--------|-------------|
| Coverage | … |
| Precision | … |
| Type accuracy | … |
| Span fidelity | … |
| Redundancy | … |

### What Works Well

1. …

### Areas of Improvement

#### 1. {Failure mode}
- examples…

### Recommendations

#### Prompt changes
…

#### Model settings (`config.yaml`)
…

#### Pipeline (non-prompt)
…

### Generic vs specific classification

| Recommendation | Scope | Target layer |
|----------------|-------|--------------|
| Verbatim span rule | Generic — all models/domains | `prompt_builder.py` structure |
| Exclude code variables | Domain — technical | `prompts/.../technical/` or `domains.technical` |
| Cloudera few-shot | Document-specific | Per-model prompt files only |
| `use_few_shot: true` | Model-tier | `llm.model_settings.{model}` |

### Priority fix order

1. …
2. …
```

## Where to patch

| Layer | Scope | Edit target |
|-------|-------|-------------|
| **Structure** | All models, all domains | `src/extraction/prompt_builder.py` — then regenerate |
| **Domain vocabulary** | Per domain | `config/config.yaml` `domains.*` + `prompts/{model}/{domain}/` |
| **Model format** | Per model | `config.yaml` `format_strictness`, `use_few_shot`, chunk sizes |
| **Concrete prompt** | Per model + domain | `prompts/{model}/{domain}/entity.*.txt` directly |

**Do not** put document-specific few-shot examples or narrow product lists into `prompt_builder.py` defaults.

After editing `prompt_builder.py` or domain config:

```bash
python main.py prompts regenerate --model {model} --domain {domain}
```

After editing prompt instance files directly, re-run extraction — no regenerate needed.

## Recommendation scoping rules

Before proposing prompt changes, classify each item:

| Scope | Belongs in | Examples |
|-------|------------|----------|
| **Generic** | Structure layer / all domains | Verbatim spans, longest-match preference, "named entities not common nouns" |
| **Domain** | `domains.{name}` + domain prompt files | Service vs Product definitions, exclude shell commands, `Document` type for "see …" links |
| **Model-tier** | `model_settings` | `format_strictness`, `use_few_shot`, smaller `chunk_size` for mid-tier models |
| **Document** | Evaluation report only, or one-off prompt edit | Cloudera version examples from one ZDU doc — not global defaults |

When the user asks to **incorporate evaluation fixes into prompts**, edit `prompts/{model}/{domain}/entity.system.txt` and `entity.user.prefix.txt` — split system rules vs few-shot user prefix per `prompts/README.md`.

## Post-extraction improvements (pipeline)

Recommend separately from prompt changes — these help all models:

1. Verbatim validation — reject entities absent from source text
2. Longest-span dedup — keep `Product X 1.2.3` over bare `Product X`
3. Domain blocklists — filter generic tokens post-hoc (technical only)
4. Resolver/markup alignment — fix orphan entities via canonical form matching

## Additional resources

- Failure mode examples and ZDU reference run: [reference.md](reference.md)
