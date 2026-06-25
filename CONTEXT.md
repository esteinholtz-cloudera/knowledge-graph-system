# Ingestion

Glossary for the **Ingestion** bounded context: documents → knowledge graphs + ontology. For system
boundaries and the artifact contract with Reasoning, see [CONTEXT-MAP.md](CONTEXT-MAP.md). Reasoning
vocabulary lives in [reasoning/CONTEXT.md](reasoning/CONTEXT.md) — not duplicated here.

This file is a glossary only — no implementation details. See `docs/` for design and ADRs for Ingestion
work (ontology, API, GUI). Reasoning ADRs live under `reasoning/docs/adr/`.

## Language

### Pipeline

**Ingestion** / **extraction pipeline**:
The subsystem that processes documents, extracts entities and relationships with an LLM, resolves entities,
writes Turtle KGs, proposes ontology classes, and produces HTML markup. Distinct from the downstream
[Reasoning](reasoning/CONTEXT.md) context.
_Avoid_: knowledge graph system (too broad — includes Reasoning)

**Knowledge graph (KG)**:
Per-document RDF triples in Turtle (`data/knowledge_graphs/`). Extraction output; not trusted for
deterministic reasoning until verified in the Reasoning context.
_Avoid_: graph (ambiguous)

**Ontology**:
Local OWL class hierarchy (`data/ontology/ontology.ttl`) used to type entities (`rdf:type`). Class proposals
are reviewed separately from Reasoning edge review.
_Avoid_: schema (ambiguous)

**SubTaxonomyProposal**:
A proposed ontology class or entity re-typing entry awaiting review (`ontology_proposed.ttl`).
_Avoid_: proposal (ambiguous)

**Predicate normalization**:
Clustering ad-hoc `kg:` predicates to a canonical vocabulary and rewriting TTL files.
_Avoid_: normalization (ambiguous)

### Operations

**Benchmark run**:
One recorded pipeline invocation in DuckDB (`data/benchmark.duckdb`) with timings and counts.
_Avoid_: run (ambiguous)

**Job**:
An async unit of work in the HTTP API (`pipeline.process`, etc.) with progress events.
_Avoid_: task (ambiguous)
