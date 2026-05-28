# Knowledge Graph System

Generate knowledge graphs from documents: extract entities and relationships with an LLM, store them as Turtle (RDF), type entities against a local ontology (`rdf:type`), and produce HTML markup linked to the graph.

## Quick start

### 1. Install

```bash
uv sync
```

### 2. Configure the LLM

Edit [`config/config.yaml`](config/config.yaml). Default is local **Ollama**:

```yaml
llm:
  provider: ollama    # ollama | lmstudio | openai | anthropic | gemini
  model: llama3.2     # must match a model you have pulled / loaded
```

| Provider | Typical setup |
|----------|----------------|
| `ollama` | Run Ollama; default API `http://localhost:11434/v1` |
| `lmstudio` | Start a model in LM Studio; default `http://localhost:1234/v1` |
| `openai` / `anthropic` / `gemini` | Set API key env var (see [`.env.example`](.env.example)) |

Verify config (no LLM call):

```bash
uv run python test/test_llm_config.py
```

Optional live check (Ollama running or API key set):

```bash
uv run python test/test_llm_config.py --live
```

### 3. Add a document to scan

Put your text (or Markdown) here:

```text
data/documents/my-doc.txt
```

Example content is fine for a first run—a few paragraphs with named entities (people, products, places).

### 4. Process the document

From the repo root:

```bash
uv run python main.py process data/documents/my-doc.txt
```

The pipeline runs in two passes:

```
Document
  │
  ▼
DocumentProcessor  ── chunk text (chunk_size / overlap)
  │
  ├─ Pass 1: Entity extraction (all chunks)
  │    └─ EntityExtractor       ── LLM → named entities with types
  │         ↓ case-insensitive dedup (HAMLET/HAmlet/hamlet → Hamlet)
  │         ↓ EntityResolver    ── rule_based / embedding / llm strategies
  │              → alternate_names recorded for each variant
  │
  ├─ Pass 2: Relationship extraction (canonical entity names as hints)
  │    └─ RelationshipExtractor ── LLM → subject–predicate–object triples
  │         ↓ subjects/objects corrected to canonical names via lookup
  │
  ├─ TurtleWriter         ── RDF Turtle (my-doc.ttl)
  │    ├─ entities → kg: URIs  (rdf:type → ont: classes)
  │    ├─ kg:alternateName for resolved variants
  │    ├─ non-entity objects → Literals
  │    └─ new types → ontology_proposed.ttl (awaiting human approval)
  │
  └─ HTMLMarkupGenerator  ── reads TTL → annotated HTML (my-doc_markup.html)
       └─ [--with-graph]  ── ttl_to_html.py → interactive graph (my-doc_graph.html)
```

Outputs for `my-doc.txt`:

1. **Knowledge graph** `data/knowledge_graphs/my-doc.ttl` — entities, triples, `rdf:type` and `kg:alternateName`
2. **HTML markup** `data/documents/my-doc_markup.html` — entities highlighted, links to graph view
3. **Ontology proposals** `data/ontology/ontology_proposed.ttl` — new classes for human review (accumulates across runs)

### 5. Check the outputs

| What | Where | What to look for |
|------|--------|------------------|
| Knowledge graph | `data/knowledge_graphs/my-doc.ttl` | Triples plus `a ont:Person` (etc.) on entities |
| HTML markup | `data/documents/my-doc_markup.html` | Open in a browser; entities highlighted with types |
| Document index | `data/metadata.json` | Maps document stem → paths and timestamps |
| Ontology | `data/ontology/ontology.ttl` | OWL classes (`ont:Person`, `ont:Technology`, …) |

**Verify ontology typing** in the TTL file:

```bash
grep "a ont:" data/knowledge_graphs/*.ttl
```

You should see lines like `kg:Some_Entity a ont:Technology ;`.

**Inspect the ontology** (classes and labels):

```bash
cat data/ontology/ontology.ttl
```

New entity types proposed during extraction accumulate in `ontology_proposed.ttl` and are merged into `ontology.ttl` only after human approval (`python main.py ontology approve`).

### 6. Optional: run without the full LLM

If the LLM is not available, you can still validate storage and HTML from a sample graph:

```bash
uv run python test/test_ontology_integration.py
```

That writes a sample `.ttl` and HTML under `data/`.

---

## Project layout

```
knowledge-graph-system/
├── config/config.yaml       # LLM, paths, chunking
├── data/
│   ├── documents/           # Input files + *_markup.html output
│   ├── knowledge_graphs/    # Generated *.ttl per document
│   ├── ontology/ontology.ttl
│   └── metadata.json
├── src/
│   ├── config/              # Settings loader
│   ├── document/            # Parsing, HTML markup
│   ├── extraction/          # LLM entity/relationship extraction
│   └── storage/             # Turtle writer, ontology manager
└── main.py                  # CLI: process | server
```

## Features

- Text, Markdown, PDF, and Word input
- Configurable LLM: Ollama, LM Studio, OpenAI, Anthropic, Gemini
- Two-pass pipeline — entities resolved before relationship extraction for consistent naming
- Case-insensitive entity dedup with `kg:alternateName` variants stored in TTL
- Entity resolution: rule-based, embedding similarity (0.92), LLM coreference
- RDF Turtle knowledge graphs with local ontology (`rdf:type`)
- Ontology proposal workflow — new classes accumulate across runs; human approval required
- HTML markup + interactive vis-network graph from TTL
- Archive command — snapshot `data/` with updated paths; benchmark DB stays in place
- Optional DuckDB benchmarking (`uv sync --extra benchmark`)
- n8n HTTP API (`python main.py server`)

## CLI reference

```bash
# Full pipeline (pre-flight check, TTL, HTML markup)
uv run python main.py process <path-to-document>

# Also generate interactive graph HTML (requires ai-knowledge-graph)
uv run python main.py process <path-to-document> --with-graph

# Limit chunks for quick testing on long documents
uv run python main.py process <path-to-document> --max-chunks 3

# Approve proposed ontology additions after reviewing ontology_proposed.ttl
uv run python main.py ontology approve

# Archive current data/ to data_save_<name>; resets data/ for the next run
uv run python main.py archive --name my_run_1
# Name the archive after the current LLM model
uv run python main.py archive --llmnamed

# View benchmark metrics (requires: uv sync --extra benchmark)
uv run python main.py benchmark show
uv run python main.py benchmark query "SELECT llm_model, avg(elapsed_s) FROM runs GROUP BY llm_model"

# n8n integration server
uv run python main.py server --port 5000
```

Supported inputs: `.txt`, `.md`, `.pdf`, `.docx`.

## Configuration

[`config/config.yaml`](config/config.yaml) controls:

- **llm** — provider, model, `base_url`, `api_key_env`, `disable_thinking`, generation limits
- **document** — `chunk_size`, `overlap`
- **storage** — directories for graphs, documents, ontology
- **entity_resolution** — `enabled`, `strategies` (rule_based / embedding / llm), `embedding_threshold`, `abbreviation_hints`
- **visualization** — `ai_kg_path` (path to `ai-knowledge-graph` for `--with-graph`)

API keys belong in the environment only (never in YAML). Copy [`.env.example`](.env.example) as a reminder.

## n8n API

With the server running:

- `GET /health`
- `POST /process` — body: `{"file_path": "...", "chunk_size": 1000, "overlap": 100}`
- `POST /extract/entities`, `POST /extract/relationships`, `POST /store`
- `GET /metadata`, `GET /metadata/<document_id>`

## Benchmarking

Pipeline metrics (entity counts, LLM timings, resolution results) are recorded to a local DuckDB database. See [docs/Benchmark.md](docs/Benchmark.md) for the schema, CLI, and example queries.

## License

See LICENSE file for details.
