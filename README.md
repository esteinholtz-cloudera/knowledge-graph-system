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
  provider: ollama    # ollama | lmstudio | openai | anthropic | gemini | subagent
  model: llama3.2     # must match a model you have pulled / loaded
```

| Provider | Typical setup |
|----------|----------------|
| `ollama` | Run Ollama; default API `http://localhost:11434/v1` |
| `lmstudio` | Start a model in LM Studio; default `http://localhost:1234/v1` |
| `openai` / `anthropic` / `gemini` | Set API key env var (see [`.env.example`](.env.example)) |
| `subagent` | Use a Cursor subagent as the LLM via the `cursor-agent` CLI. Install the [Cursor CLI](https://docs.cursor.com/en/cli/overview) and run `cursor-agent login`. `model` maps to `cursor-agent --model` (use an id from `cursor-agent --list-models`, e.g. `claude-4-sonnet`); leave `null` for the subagent default. |

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
│   ├── services/            # Orchestration (CLI, future HTTP API)
│   ├── config/              # Settings loader
│   ├── document/            # Parsing, HTML markup
│   ├── extraction/          # LLM entity/relationship extraction
│   └── storage/             # Turtle writer, ontology manager
└── main.py                  # Thin CLI dispatch → services
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

# HTTP API + legacy n8n routes (port from config/config.yaml, default 5001)
uv run python main.py server
```

Supported inputs: `.txt`, `.md`, `.pdf`, `.docx`.

## Configuration

[`config/config.yaml`](config/config.yaml) controls:

- **llm** — provider, model, `base_url`, `api_key_env`, `disable_thinking`, generation limits
- **document** — `chunk_size`, `overlap`
- **storage** — directories for graphs, documents, ontology
- **entity_resolution** — `enabled`, `strategies` (rule_based / embedding / llm), `embedding_threshold`, `abbreviation_hints`
- **visualization** — `ai_kg_path` (path to `ai-knowledge-graph` for `--with-graph`)
- **pipeline** — `max_concurrent_llm_calls` (default `1`; raise for cloud APIs)

API keys belong in the environment only (never in YAML). Copy [`.env.example`](.env.example) as a reminder.

## HTTP API

With `uv run python main.py server` running, the GUI and integrations should use **`/api/v1`**.

Domain shapes (entities, triples, jobs, API payloads) are documented in [docs/INFOMODEL.md](docs/INFOMODEL.md).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health/precheck` | LLM/embed preflight (JSON) |
| `GET` | `/api/v1/config` | Sanitized config (no secrets) |
| `POST` | `/api/v1/jobs/pipeline` | Start full pipeline → `{ "job_id" }` |
| `GET` | `/api/v1/jobs/<id>` | Job status + result |
| `GET` | `/api/v1/jobs/<id>/events` | SSE progress stream |
| `POST` | `/api/v1/jobs/<id>/cancel` | Request cancellation |
| `GET` | `/api/v1/documents` | List processed documents |
| `POST` | `/api/v1/documents/upload` | Upload to `data/documents/` |
| `GET` | `/api/v1/artifacts/<id>/kg` | Download TTL |

Example:

```bash
# Start pipeline (async)
curl -s -X POST http://127.0.0.1:5001/api/v1/jobs/pipeline \
  -H 'Content-Type: application/json' \
  -d '{"file_path":"data/documents/my-doc.txt","with_graph":true}'

# Stream progress (replace JOB_ID)
curl -N http://127.0.0.1:5001/api/v1/jobs/JOB_ID/events
```

Legacy n8n routes (`POST /process`, `GET /metadata`, …) remain at `/` with a `Deprecation` header; prefer `/api/v1`.

**Review and admin (Phase 4):**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ontology/status` | Proposal summary |
| `PATCH` | `/api/v1/ontology/proposals/{uri}` | Approve/reject, set parent class |
| `POST` | `/api/v1/ontology/proposals/{uri}/suggest-placement` | LLM + Wikidata suggestions |
| `POST` | `/api/v1/ontology/approve` | Merge approved into `ontology.ttl` |
| `GET` | `/api/v1/normalize/map` | Read predicate map |
| `PATCH` | `/api/v1/normalize/map/groups/{canonical}` | Mark group reviewed |
| `POST` | `/api/v1/normalize/apply` | Apply map (`dry_run` optional) |
| `GET` | `/api/v1/benchmark/runs` | Benchmark tables as JSON |
| `POST` | `/api/v1/archive` | Archive `data/` |

Encode proposal URIs in paths with `urllib.parse.quote(uri, safe="")`.

## Web GUI (Phase 5)

**One command** (reads `n8n.port` and `gui.port` from [`config/config.yaml`](config/config.yaml)):

```bash
./scripts/start-dev.sh
# or: uv run python scripts/start_dev.py
```

Opens the GUI in your default browser (`open` on macOS) once Vite is ready. Use `--no-browser` to skip.

**Manual** (two terminals):

```bash
# Terminal 1 — API (default port 5001 in config)
uv run python main.py server

# Terminal 2 — UI (proxies /api → API port via KGS_API_PORT)
cd gui && npm install && KGS_API_PORT=5001 npm run dev
```

Open http://localhost:5173. See [gui/README.md](gui/README.md) for build and route details.

On macOS, port 5000 is often taken by AirPlay Receiver; the default API port is **5001** to avoid that conflict.

## Documentation

| Doc | Contents |
|-----|----------|
| [CONTEXT-MAP.md](CONTEXT-MAP.md) | Ingestion vs Reasoning boundaries and artifact contract |
| [CONTEXT.md](CONTEXT.md) | Ingestion glossary |
| [docs/INFOMODEL.md](docs/INFOMODEL.md) | Internal information model — interconnection schema, domain objects, `/api/v1` mapping |
| [docs/ONTOLOGY.md](docs/ONTOLOGY.md) | Ontology workflow, OWL structure, CLI review |
| [docs/Benchmark.md](docs/Benchmark.md) | DuckDB benchmark schema and queries |
| [docs/GUI_API_PLAN.md](docs/GUI_API_PLAN.md) | HTTP API and GUI architecture (Ingestion) |
| [reasoning/README.md](reasoning/README.md) | Reasoning bounded context — ADRs and glossary |
| [gui/README.md](gui/README.md) | Web UI setup and routes |

## Ontology management

The system maintains a local OWL ontology that types all extracted entities. New classes are proposed during extraction and reviewed interactively with LLM placement suggestions and Wikidata alignment. See [docs/ONTOLOGY.md](docs/ONTOLOGY.md) for the full workflow, CLI reference, and configuration.

## Benchmarking

Pipeline metrics (entity counts, LLM timings, resolution results) are recorded to a local DuckDB database. See [docs/Benchmark.md](docs/Benchmark.md) for the schema, CLI, and example queries.

## License

See LICENSE file for details.
