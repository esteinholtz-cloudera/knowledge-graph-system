# Convergence Indicators — Design Notes

## Why a composite score?

Individual gates catch different failure modes. A single metric (e.g. orphan rate) can look good while precision is poor, or vice versa. The weighted `error_score` tracks overall progress across iterations; gates prevent declaring victory on a lucky partial fix.

## Indicator reference

### 1. `verbatim_rate` (high priority)

**Formula:** `verbatim_issues / unique_entities`

**Threshold:** ≤ 5%

**Rationale:** Entities must appear exactly in source text for KG linking. Paraphrase (`Atlas Hook` vs `ATLAS_HOOK`) and casing drift (`Hdfs` vs `HDFS`) break downstream TTL and markup.

**Limitation:** Case-insensitive substring matches count as `case_or_spacing_drift`, not hard failure — still penalized in rate.

### 2. `orphan_rate` (high priority, interpret carefully)

**Formula:** entities in sidebar list but never marked in document / unique entities

**Threshold:** ≤ 10%

**Rationale:** Surfaces resolver/canonical-form vs markup mismatches and truncated spans.

**Limitation:** Prompt-only loops may **not** reduce this below ~10% if the issue is in `html_markup.py` or entity resolution — watch for plateau with high orphan_rate and stop the loop.

### 3. `other_rate` (medium priority)

**Formula:** `Other` type count / unique entities

**Threshold:** ≤ 10%

**Rationale:** Domain-specific types exist in the prompt; heavy `Other` use means the model is not applying the taxonomy (common on mid-tier models).

### 4. `generic_hit_rate` (medium priority)

**Formula:** entities matching operational blocklist / unique entities

**Threshold:** ≤ 3%

**Blocklist (technical):** restart, topic, read-only, follower replica, leader replica, external clients, source cluster, migration of metrics, service role types, kafka topics

**Rationale:** Cheap proxy for precision on ops-heavy docs without manual review each iteration.

**Limitation:** Domain-specific — use empty blocklist or disable gate for literary text.

### 5. `error_score` (tracking + gate)

**Formula:**

```
0.30 × orphan_rate + 0.30 × verbatim_rate + 0.20 × other_rate + 0.20 × generic_hit_rate
```

**Threshold:** ≤ 0.12

**Rationale:** Single number for iteration comparison and benchmark trending.

### 6. `grade_score` (qualitative guardrail)

**Source:** Letter grade from llm-as-judge-EE mapped to numeric (B+ = 87, B- = 80, etc.)

**Threshold:** ≥ 85 (B+)

**Rationale:** Catches failure modes the script does not measure (missing recall, redundancy clusters, wrong types with verbatim spans).

**Limitation:** Requires judge step each iteration — do not automate loop without it.

## Plateau detection

**Condition:** `error_score` improves by less than `0.02` vs previous iteration.

**Meaning:** Further prompt edits are unlikely to help. Common causes:

- Pipeline/resolver ceiling (orphans)
- Model instruction-following limit
- Document-specific gaps already covered in few-shot

**Action:** Stop loop; report best iteration; suggest pipeline fixes or gold-standard labels.

## Suggested starting thresholds by domain

| Domain | orphan | verbatim | other | generic | error_score | grade |
|--------|--------|----------|-------|---------|-------------|-------|
| technical | 10% | 5% | 10% | 3% | 0.12 | 85 |
| default | 10% | 5% | 15% | 5% | 0.15 | 83 |
| literary | 15% | 5% | 20% | — | 0.18 | 80 |

## Future indicators (not yet automated)

- **Recall proxy:** fraction of heading-level service names in source that appear in entity list
- **Redundancy cluster count:** abbrev + full-form pairs (ZDU / Zero Downtime Upgrade)
- **Version fragmentation score:** product/version split inconsistency
- **Coverage metric:** fraction of source words covered by at least one entity span (see `TODO.md`)
