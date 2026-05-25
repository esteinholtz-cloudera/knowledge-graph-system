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

The pipeline:

1. Builds a **knowledge graph** (`.ttl`) with entities, relationships, and `rdf:type` links to the ontology  
2. Writes **HTML markup** with entities highlighted (`data/documents/my-doc_markup.html`)

### 5. Check the outputs

| What | Where | What to look for |
|------|--------|------------------|
| Knowledge graph | `data/knowledge_graphs/<hash>.ttl` | Triples plus `a ont:Person` (etc.) on entities |
| HTML markup | `data/documents/my-doc_markup.html` | Open in a browser; entities highlighted with types |
| Document index | `data/metadata.json` | Maps document hash → paths and timestamps |
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

New entity types from extraction are added to this file automatically when needed.

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
- RDF Turtle knowledge graphs with local ontology (`rdf:type`)
- HTML document markup generated from the TTL
- n8n HTTP API (`python main.py server`)

## CLI reference

```bash
# Full pipeline: TTL then HTML
uv run python main.py process <path-to-document>

# n8n integration server
uv run python main.py server --port 5000
```

Supported inputs: `.txt`, `.md`, `.pdf`, `.docx`.

## Configuration

[`config/config.yaml`](config/config.yaml) controls:

- **llm** — provider, model, `base_url`, `api_key_env`, generation limits  
- **document** — `chunk_size`, `overlap`  
- **storage** — directories for graphs, documents, ontology  

API keys belong in the environment only (never in YAML). Copy [`.env.example`](.env.example) as a reminder.

## n8n API

With the server running:

- `GET /health`
- `POST /process` — body: `{"file_path": "...", "chunk_size": 1000, "overlap": 100}`
- `POST /extract/entities`, `POST /extract/relationships`, `POST /store`
- `GET /metadata`, `GET /metadata/<document_id>`

## License

See LICENSE file for details.
