# Entity Extraction Tuning Metrics

Quantitative metrics used by the LLM-as-judge EE workflow and the EE calibration loop to measure extraction quality and track prompt-tuning progress.

Related docs: [Benchmark.md](Benchmark.md) (DuckDB schema), [PROMPT_TUNING.md](PROMPT_TUNING.md) (prompt axes).

---

## Where the numbers come from

All quantitative metrics are computed from two files:

1. **Markup HTML** (`*_markup.html`) — the pipeline’s annotated document
2. **Source text** (`input/...txt`) — the original document

`analyze_markup.py` parses the markup and compares it to the source. The calibration loop then derives rates and `error_score` in `check_convergence.py`.

The markup HTML has two relevant views of entities:

- **Entity list** (sidebar) — every unique entity the extractor claimed, with a type
- **Marked spans** (inline in the text) — entities actually highlighted in the document body

Implementation: `.cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py`

---

## Orphan rate

**What it measures:** Entities that appear in the sidebar list but are **never marked inline** in the document.

**Formula:** `orphan_entities / unique_entities`

**Example (ZDU baseline, default prompts):** 37 orphans / 144 entities = **25.7%**

**What it usually means:**

- The model extracted an entity, but markup/linking could not place it in the text
- Common causes: canonical-form mismatch (`Atlas Hook` extracted, but source says `ATLAS_HOOK`), truncated spans, resolver merging names differently than the extractor, or markup anchor logic missing a match

**Important caveat:** A high orphan rate is not always a prompt problem. Much of it can live in `html_markup.py` or entity resolution. Prompt-only tuning may plateau around ~10–25% even when extraction quality improves.

**Target (technical domain):** ≤ 10%

---

## Verbatim rate

**What it measures:** How often extracted entity **names** do not appear exactly in the source text.

**Formula:** `verbatim_issues / unique_entities`

**How a “verbatim issue” is detected:**

| Sub-type | Condition |
|----------|-----------|
| `case_or_spacing_drift` | Entity not found exactly, but a case-insensitive match exists (`Hdfs` vs `HDFS`, `7.1.9 Sp1` vs `7.1.9 SP1`) |
| `not_in_source` | No match even case-insensitively — paraphrased or invented (`Atlas Entities` when the doc only mentions `ATLAS_HOOK`) |

**Example (ZDU baseline):** 21 issues / 144 entities = **14.6%**

**Why it matters:** Knowledge graphs and downstream linking expect spans copied from the document. Paraphrase breaks TTL alignment and markup matching.

**Target (technical):** ≤ 5%

> **Note — case & spacing drift are corrected in postprocessing, not prompts.**
> `case_or_spacing_drift` issues (`Hdfs` vs `HDFS`, `7.1.9  SP1` vs `7.1.9 SP1`)
> are not worth prompt-tuning for. Entity dedup (`PipelineService._dedupe_entities`)
> collapses case/spacing variants to one canonical surface form (acronyms preserved),
> and the markup correlator (`HTMLMarkupGenerator._find_entity_matches`) matches
> case- and spacing-insensitively. Only `not_in_source` (genuine paraphrase/invention)
> is a prompt-quality signal.

**Note:** The benchmark DB stores the raw count (`verbatim_issues`); `verbatim_rate` is computed when checking convergence.

---

## Other rate

**What it measures:** How often the model falls back to the catch-all type **`Other`** instead of using the domain taxonomy (Technology, Product, Concept, Version, etc.).

**Formula:** `count(type == "Other") / unique_entities`

**Example (ZDU baseline):** 23 Other / 144 entities = **16.0%**

**What it usually means:**

- Weak type disambiguation
- The model is unsure and picks the safe bucket
- Often correlates with mid-tier models or under-specified prompts

**Target (technical):** ≤ 10%

---

## Generic hit rate

**What it measures:** Fraction of entities matching a small **blocklist of low-value operational phrases** used as a cheap precision proxy on ops-heavy docs.

**Formula:** `generic_hits / unique_entities`

**Blocklist (technical):** `restart`, `topic`, `read-only`, `follower replica`, `leader replica`, `external clients`, `source cluster`, `migration of metrics`, `service role types`, `kafka topics`

**Target (technical):** ≤ 3%

Literary or scientific domains may use an empty blocklist or disable this gate via domain-specific thresholds.

---

## Error score

**What it measures:** A single weighted composite of the four automated error signals above. Used to compare runs and detect calibration progress or plateau.

**Formula:**

```
error_score = 0.30 × orphan_rate
            + 0.30 × verbatim_rate
            + 0.20 × other_rate
            + 0.20 × generic_hit_rate
```

**Target (technical):** ≤ **0.12** (lower is better)

**Plateau detection:** If `error_score` improves by less than **0.02** vs the previous iteration, the calibration loop treats progress as stalled.

Implementation: `.cursor/skills/ee-calibration-loop/scripts/check_convergence.py`

Default thresholds: `.cursor/skills/ee-calibration-loop/thresholds-technical.json`

---

## Baseline example (ZDU, default prompts, grade B−)

| Metric | Value | Gate (technical) | Pass? |
|--------|-------|------------------|-------|
| Orphan rate | 25.7% | ≤ 10% | No |
| Verbatim rate | 14.6% | ≤ 5% | No |
| Other rate | 16.0% | ≤ 10% | No |
| Generic hit rate | 6.9% | ≤ 3% | No |
| Error score | **0.167** | ≤ 0.12 | No |
| Grade | **B−** (80) | ≥ B+ (85) | No |

The baseline was the best run on entity count and orphan rate among calibrated variants, but still far from automated convergence gates. The B− grade reflects qualitative judgment (usable but noisy) and catches failure modes the scripts do not measure well: missing recall, redundancy clusters (`ZDU` + `Zero Downtime Upgrade` + `ZDU process`), wrong types on otherwise verbatim spans, version fragmentation, etc.

---

## How the pieces fit together

```
markup HTML + source text
        │
        ▼
 analyze_markup.py
   • unique_entities, marked_spans
   • orphan_rate, verbatim_issues
   • type_distribution_unique
        │
        ▼
 check_convergence.py
   • verbatim_rate, other_rate, generic_hit_rate
   • error_score + gate pass/fail
        │
        ▼
 ee_judge_evaluations (DuckDB)
   • grade, summary, scalar columns
   • full metrics_json blob
```

**Stored in `ee_judge_evaluations`:** grade, summary, scalar columns (`orphan_rate`, `verbatim_issues`, etc.), and full `metrics_json`.

**Computed at calibration time:** `verbatim_rate`, `other_rate`, `generic_hit_rate`, and `error_score` — not separate DB columns, but available from the convergence check output.

---

## Running the metrics locally

```bash
# Raw markup analysis
uv run python .cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py \
  data/documents/ZDU_prereqs_markup.html \
  input/ZDU_prereqs.txt \
  --json

# Convergence check (rates + error_score + gates)
uv run python .cursor/skills/ee-calibration-loop/scripts/check_convergence.py \
  --metrics-file /tmp/metrics.json \
  --markup data/documents/ZDU_prereqs_markup.html \
  --grade-score 80 \
  --thresholds-file .cursor/skills/ee-calibration-loop/thresholds-technical.json
```

---

## Suggested thresholds by domain

| Domain | orphan | verbatim | other | generic | error_score | grade |
|--------|--------|----------|-------|---------|-------------|-------|
| technical | 10% | 5% | 10% | 3% | 0.12 | 85 (B+) |
| default | 10% | 5% | 15% | 5% | 0.15 | 83 (B) |
| literary | 15% | 5% | 20% | — | 0.18 | 80 (B−) |

Design notes: `.cursor/skills/ee-calibration-loop/convergence-indicators.md`
