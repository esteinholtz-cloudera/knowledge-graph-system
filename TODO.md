# TODO

## Ontology

- Property definitions (`owl:ObjectProperty`) with `rdfs:domain` / `rdfs:range` — next sprint
- External ontology import (`owl:imports`)

## Extraction / LLM calibration

- **Calibration tool** — automated sweep of `chunk_size`, `overlap`, `section_size` per model
  to find the combination that maximises entity/triple yield per token. Uses benchmark DB to compare runs.
- **Prompt calibration** — systematic A/B of entity and relationship extraction prompts
  (few-shot examples, CoT, output format variants) measured against a labelled gold-standard document.
- **Coverage metric** — fraction of source text covered by at least one entity mention;
  makes lost-in-the-middle degradation quantitative and comparable across runs.

## Pipeline

- Pass 3: document-level concept extraction (overarching relationships across all sections)
- Relationship deduplication: merge near-duplicate predicates (e.g. `uses` / `utilises`)
- **Chunking strategy**: evaluate sentence/paragraph boundary splitting vs current word-count
  splitting — boundary-aware chunks avoid cutting mid-sentence and may improve extraction quality
