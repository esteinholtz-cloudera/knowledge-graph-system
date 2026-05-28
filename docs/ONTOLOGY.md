# Ontology Management

The system maintains a local OWL ontology at `data/ontology/ontology.ttl` that types all extracted entities via `rdf:type`. This document describes the ontology structure, the proposal workflow, and the interactive review process.

---

## Ontology structure

The ontology is a proper OWL file using standard namespaces:

```turtle
@prefix ont: <http://example.org/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ont:Technology a owl:Class ;
    rdfs:label "Technology" ;
    rdfs:comment "A technology, tool, or platform" ;
    rdfs:subClassOf owl:Thing .         ← class hierarchy

ont:MCP_Server a owl:Class ;
    rdfs:label "MCP Server" ;
    rdfs:subClassOf ont:Technology ;    ← placed by reviewer
    owl:equivalentClass wd:Q107429595 . ← Wikidata alignment
```

### Base classes

| Class | Description |
|---|---|
| `ont:Person` | A human being or individual |
| `ont:Organization` | A company, institution, or group |
| `ont:Location` | A geographical place or location |
| `ont:Technology` | A technology, tool, or platform |
| `ont:Concept` | An abstract concept or idea |
| `ont:Product` | A product or service |
| `ont:Event` | An event or occurrence |
| `ont:Date` | A date or time period |
| `ont:Other` | Other type of entity |

New classes are added via the proposal and review workflow below.

---

## How classes are proposed

During document processing, the pipeline detects two kinds of new classes:

1. **Entity types** — when the LLM assigns a type not in the ontology (e.g. `type: "Framework"`)
2. **Is-a triples** — when relationship extraction returns an is-a pattern (e.g. `"MCP Server isA Technology"`) that implies a new class

These are collected in `data/ontology/ontology_proposed.ttl` — a **differential** file containing only the additions, not the full ontology.

### Proposal file format

```turtle
# ontology_proposed.ttl — DIFFERENTIAL additions only
#
# Review interactively:  python main.py ontology review
# Bulk approve all:      python main.py ontology approve

@prefix ont: <http://example.org/ontology/> .
@prefix ont_meta: <http://example.org/ontology/meta/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

ont:MCP_Server a owl:Class ;
    rdfs:label "MCP Server" ;
    rdfs:comment "Proposed from: MCP.txt (triple: Git MCP Server isA MCP Server)" ;
    ont_meta:proposedBy "MCP.txt" ;
    ont_meta:reviewStatus "pending" .    ← pending | approved | rejected
```

Proposals **accumulate across runs** — reprocessing a document never overwrites unapproved proposals from a previous run.

---

## Ontology CLI commands

```bash
# Show pending proposals and counts
python main.py ontology status

# Interactive review (recommended)
python main.py ontology review

# Bulk-approve all pending proposals without interaction
python main.py ontology approve
```

---

## Interactive review (`ontology review`)

Walks through each pending class one at a time. For each class the system:

1. Queries **Wikidata** (via MCP) to find matching entities and their superclass chain
2. Asks the **LLM** to generate 3 ranked `rdfs:subClassOf` placements
3. Presents the options to the user

### Example session

```
════════════════════════════════════════════════════════════
  1/2  ont:MCP_Server
  Source: MCP.txt
  Context: Proposed from: MCP.txt (triple: Git MCP Server isA MCP Server)
════════════════════════════════════════════════════════════

  Wikidata matches:
    1. Q107429595  "software server" — a server is a piece of software...
    2. Q7397       "software" — instructions that direct a computer...

  LLM placement proposals (ranked by confidence):

  a) [93%]  rdfs:subClassOf ont:Technology
            "An MCP Server is a type of technology/software"

  b) [71%]  rdfs:subClassOf ont:Product
            "MCP Server as a deployable software product"

  c) [44%]  rdfs:subClassOf owl:Thing
            "Top-level class — no hierarchy constraint"

  d) Try again   s) Search Wikidata   m) Specify manually   r) Reject

  Choice [a/b/c/d/s/m/r]:
```

### Choice reference

| Key | Action |
|---|---|
| `a` / `b` / `c` | Accept the corresponding LLM proposal — writes `rdfs:subClassOf` |
| `d` | Re-ask the LLM (generates 3 new options) |
| `s` | **Search** Wikidata by name — enter a search term, pick a result; the system infers `rdfs:subClassOf` from the P279 chain and records `owl:equivalentClass wd:Qxxxx` |
| `m` | **Manual** — enter a parent URI directly (e.g. `ont:Technology` or a full URI) |
| `r` | **Reject** — mark as rejected; class is not added to the ontology |

After all classes are reviewed, approved classes are **merged** into `ontology.ttl` (not replaced — the file is updated by adding the new triples). The proposal file is cleaned up.

---

## Wikidata integration

The system launches the [mcp-wikidata](https://github.com/esteinholtz-cloudera/mcp-wikidata) server as a subprocess via `uvx`:

```
uvx --from git+https://github.com/esteinholtz-cloudera/mcp-wikidata mcp-wikidata
```

No separate installation is required — `uvx` fetches and runs it on demand.

### Available Wikidata tools

| Tool | Use in ontology review |
|---|---|
| `search_entity(query)` | Find Wikidata entities matching a class label |
| `get_metadata(entity_id)` | Get label + description for display |
| `execute_sparql(query)` | Fetch P279 superclasses to infer `rdfs:subClassOf` |

### Configuration

```yaml
# config/config.yaml
ontology:
  wikidata_mcp: subprocess   # subprocess | http | disabled
  wikidata_mcp_url: null     # only used when mode=http (future)
```

Set `wikidata_mcp: disabled` to skip Wikidata lookups entirely (LLM proposals still work).

---

## Approval

`python main.py ontology approve` bulk-approves all pending proposals without interaction. Use this for CI or when you have reviewed the proposal file manually and are confident in the defaults.

Approval **merges** new triples into `ontology.ttl` — existing classes are never removed or overwritten.

---

## Ontology in the knowledge graph TTL

Each knowledge graph file links to the ontology via `rdf:type`:

```turtle
kg:MCP_Server a ont:MCP_Server ;          ← instance typed against ontology class
    kg:alternateName "MCP server" ;        ← case variants from entity resolution
    doc:sourceDocument doc:MCP .
```

Predicates (relationships) currently use ad-hoc `kg:` URIs. A future sprint will add `owl:ObjectProperty` definitions with `rdfs:domain` / `rdfs:range` to the ontology.

---

## Roadmap

| Feature | Status |
|---|---|
| Class hierarchy (`rdfs:subClassOf`) | ✓ Via interactive review |
| Wikidata alignment (`owl:equivalentClass`) | ✓ Via `s` option |
| Proposal accumulation across runs | ✓ |
| Property definitions (`owl:ObjectProperty`), external ontology import | See `TODO.md` |
