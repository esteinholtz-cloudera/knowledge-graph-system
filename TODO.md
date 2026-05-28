# TODO

## Ontology

- Property definitions (`owl:ObjectProperty`) with `rdfs:domain` / `rdfs:range` — next sprint
- External ontology import (`owl:imports`)
- **Axioms and rules** — add OWL axioms (e.g. disjointness, transitivity, inverse properties) and SWRL/SHACL rules as a basis for inference over the knowledge graph

## Extraction / LLM calibration

- **Calibration tool** — automated sweep of `chunk_size`, `overlap`, `section_size` per model
  to find the combination that maximises entity/triple yield per token. Uses benchmark DB to compare runs.
- **Prompt calibration** — systematic A/B of entity and relationship extraction prompts
  (few-shot examples, CoT, output format variants) measured against a labelled gold-standard document.
- **Coverage metric** — fraction of source text covered by at least one entity mention;
  makes lost-in-the-middle degradation quantitative and comparable across runs.

## Pipeline

- Pass 3: document-level concept extraction (overarching relationships across all sections)
- **Predicate normalization** — periodic pass that clusters ad-hoc predicates by embedding
  similarity, maps clusters to a canonical controlled vocabulary via LLM, and rewrites TTL files;
  generates `owl:subPropertyOf` declarations so existing predicates remain valid under inference
- **N-ary relationship reification** — RE prompt emits optional `scope` / `strength` fields;
  TTL writer reifies these into intermediate `ont:QualifiedRelation` nodes (W3C n-ary pattern)
  enabling queries like "what requires HighAvailability for Kafka?"
- **Chunking strategy**: evaluate sentence/paragraph boundary splitting vs current word-count
  splitting — boundary-aware chunks avoid cutting mid-sentence and may improve extraction quality
