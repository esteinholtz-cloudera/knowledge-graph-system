# Honing the Knowledge Graph

This document describes the periodic refinement procedures that improve the quality
of accumulated knowledge graphs — specifically **predicate normalisation** and
**n-ary relationship reification**.

---

## Why honing is needed

The extraction pipeline gives the LLM freedom to name relationships. Over many documents
this produces *predicate explosion*: dozens of ad-hoc predicates that encode context in
their name rather than as separate attributes.

Example from ZDU_prereqs.txt:
```
requiresHighAvailabilityForKafka
requiresHighAvailabilityForPhoenix
requiresHighAvailabilityForKudu
mustRunInHighAvailabilityMode
requiresHATModeEnabled
shouldRunInHA
```

These are all semantically `requires`, scoped to a component.  Until they are normalised:
- SPARQL queries must enumerate every variant
- Reasoners cannot unify them
- The ontology cannot declare `rdfs:domain` / `rdfs:range`

---

## N-ary relationships

### The problem

RDF is binary: every triple is `(subject, predicate, object)`.  Many domain
relationships are inherently ternary or quaternary:

```
ZDU  requiresHighAvailabilityForKafka  Cloudera
```

is really:

```
(ZDU, requires, HighAvailability, scope=Kafka, strength=mandatory)
```

### The solution: QualifiedRelation intermediate node (W3C n-ary pattern)

When the LLM emits a triple with an optional `scope` field, the TTL writer
reifies it into an intermediate node:

```turtle
# Input from LLM:
# { "subject": "ZDU", "predicate": "requires",
#   "object": "High Availability", "scope": "Kafka", "strength": "mandatory" }

kg:ZDU kg:hasQualifiedRelation kg:rel_a1b2c3d4e5 .

kg:rel_a1b2c3d4e5 a ont:QualifiedRelation ;
    kg:predicate  "requires" ;
    kg:object     kg:High_Availability ;
    kg:scope      kg:Kafka ;
    kg:strength   "mandatory" ;
    doc:sourceDocument doc:ZDU_prereqs .
```

The relation node URI is a deterministic MD5 hash of `subject|predicate|object|scope`
so re-processing the same document is idempotent.

### SPARQL query pattern

```sparql
# Find everything ZDU requires, and what component it's scoped to:
SELECT ?object ?scope ?strength WHERE {
  kg:ZDU kg:hasQualifiedRelation ?r .
  ?r kg:predicate "requires" ;
     kg:object ?object ;
     kg:scope  ?scope .
  OPTIONAL { ?r kg:strength ?strength . }
}
```

### How the LLM produces scope

The relationship extraction prompt now includes:
- A controlled predicate vocabulary (18 canonical verbs)
- Optional `scope` and `strength` fields with examples

Triples without `scope` are written as plain binary triples (unchanged behaviour).
The pipeline is fully backward-compatible.

---

## Predicate normalisation

### Workflow

```
python main.py normalize scan          # Step 1: analyse + write predicate_map.yaml
# → review and edit data/predicate_map.yaml
python main.py normalize apply         # Step 2: rewrite TTL files + update ontology
```

### Step 1: scan

Scans all `data/knowledge_graphs/*.ttl` files.  For each `kg:` predicate:
- Counts occurrences across all files
- Clusters predicates by string similarity (camelCase-split edit distance ≥ 0.6)
- Optionally asks the LLM to pick the best canonical predicate for each cluster

Writes `data/predicate_map.yaml`:

```yaml
version: 1
mappings:
  - canonical: requires
    variants:
      - requiresHighAvailabilityForKafka
      - requiresHighAvailabilityForPhoenix
      - mustRunInHighAvailabilityMode
      - requiresHATModeEnabled
    total_uses: 42
    reason: "All express a conditional requirement"
    reviewed: false      ← set to true to include in apply step

  - canonical: hasVersion
    variants:
      - hasVersion717Sp2
      - hasVersion718WithLatestCHF
      - hasVersion731
    total_uses: 8
    reason: "All encode a version relationship"
    reviewed: false
```

### Step 2: review the map

Open `data/predicate_map.yaml`.  For each cluster:
- Verify the `canonical` predicate is correct (edit if not)
- Set `reviewed: true`

Leave `reviewed: false` for clusters you want to skip.

### Step 3: apply

For each reviewed mapping:
1. **Rewrites TTL files** — replaces variant predicates with the canonical form
2. **Appends to `ontology.ttl`** — declares each variant as `owl:subPropertyOf canonical`:

```turtle
kg:requiresHighAvailabilityForKafka
    a owl:ObjectProperty ;
    owl:subPropertyOf kg:requires .
```

This means even TTL files from previous runs (before rewriting) produce correct
inference results via a reasoner, because the subproperty chain is declared.

### Options

```
--dry-run    Show what would change without writing any files
--no-llm     Use string similarity only (no LLM suggestions)
--kg-dir     Path to TTL directory (default: data/knowledge_graphs)
--map-file   Path to predicate map (default: data/predicate_map.yaml)
```

---

## Recommended cadence

| Trigger | Action |
|---|---|
| After processing 5+ documents | `normalize scan` to see predicate growth |
| Before an ontology review sprint | `normalize scan` + `normalize apply` reviewed clusters |
| After adding a new document domain | Check if the controlled vocabulary needs new canonical verbs |
| Quarterly | Full review of `predicate_map.yaml`, retire obsolete predicates |

---

## Ontology properties (future)

Once predicates are normalised, add `owl:ObjectProperty` definitions with
`rdfs:domain` and `rdfs:range` for the canonical predicates.  A reasoner will
then infer entity types from their roles:

```turtle
kg:requires
    a owl:ObjectProperty ;
    rdfs:domain ont:Product ;
    rdfs:range  ont:Capability .
```

Any entity that appears as the subject of `kg:requires` is inferred to be
an `ont:Product`, even if no explicit `rdf:type` was extracted.

See `TODO.md` for planned implementation.
