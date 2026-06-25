# Context map

Two bounded contexts share a repository but must stay separable in code and documentation.

```
┌─────────────────────────────────────┐     published artifacts      ┌──────────────────────────────┐
│  Ingestion (repo root)              │ ────────────────────────────► │  Reasoning (`reasoning/`)     │
│  documents → KG + ontology          │   TTL, ontology, metadata     │  verified facts + rules →     │
│  `src/`, `gui/`, `docs/`            │   (contract below)            │  traces + reliable answers    │
└─────────────────────────────────────┘                               └──────────────────────────────┘
```

## Ingestion (mother project)

**Scope:** LLM extraction, entity resolution, predicate normalization, ontology class review, TTL/HTML
output, HTTP API, GUI.

**Code:** `src/`, `main.py`, `gui/`, `config/`, `prompts/`

**Design docs:** `CONTEXT.md` (glossary), `docs/` (INFOMODEL, ONTOLOGY, GUI plans, …)

**Must not:** import from `reasoning/`; host Reasoning ADRs or reasoning implementation.

## Reasoning (subtree)

**Scope:** Answer questions by deterministic search over **human-verified** instance facts in a
**Reasoning Vocabulary**, subject to authored **Rules**; render a **Reasoning Trace** to prose with an LLM.

**Code:** `reasoning/src/` (future), `reasoning/data/` (verified TTL)

**Design docs:** `reasoning/CONTEXT.md`, `reasoning/docs/adr/`

**Must not:** depend on Ingestion internals (`src/extraction/`, pipeline services, etc.). May read parent
**published artifacts** only.

## Published artifact contract (Ingestion → Reasoning)

Reasoning consumes a stable, versioned **surface** from Ingestion. Everything else is private.

| Artifact | Location (today) | Reasoning use |
|----------|------------------|---------------|
| Per-document KG | `data/knowledge_graphs/*.ttl` | Seed candidates for edge review (not queried directly at answer time) |
| Ontology classes | `data/ontology/ontology.ttl` | Entity typing alignment, `SoftwareVersion` / `Product` shapes |
| Document metadata | `data/metadata.json` | Provenance links for grounding |

Reasoning **does not** read raw extraction output at query time. Verified edges live in `reasoning/data/`
after human review (see [reasoning/docs/adr/0001-reasoning-substrate.md](reasoning/docs/adr/0001-reasoning-substrate.md)).

## Documentation rules

| Write here | About |
|------------|--------|
| `docs/` | Ingestion pipeline, API, GUI, ontology workflow |
| `reasoning/docs/` | Reasoning architecture, ADRs, future reasoning API/GUI plans |
| `CONTEXT-MAP.md` | Boundaries and artifact contract only |

Cross-references are allowed (e.g. a Reasoning ADR may cite parent `TODO.md`). Reasoning design docs must
not be placed in parent `docs/`.

## Glossary index

| Context | Glossary |
|---------|----------|
| Ingestion | [CONTEXT.md](CONTEXT.md) |
| Reasoning | [reasoning/CONTEXT.md](reasoning/CONTEXT.md) |
