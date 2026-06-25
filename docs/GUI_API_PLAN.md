# GUI & API Execution Plan

Design for exposing the **Ingestion** pipeline to a GUI (or any HTTP client) without wrapping CLI subprocesses. The CLI remains a thin client over the same service layer. Reasoning is out of scope — see [CONTEXT-MAP.md](../CONTEXT-MAP.md) and [reasoning/](../reasoning/).

**Implementation breakdown (tickets, file list, week-by-week order):** [GUI_IMPLEMENTATION_PLAN.md](./GUI_IMPLEMENTATION_PLAN.md)

**Internal information model (interconnection schema, domain objects, API mapping, change checklist):** [INFOMODEL.md](./INFOMODEL.md)

## Goals

1. **Single code path** — CLI, HTTP API, and future GUI call the same services.
2. **Long-running work as jobs** — `process` can take minutes; APIs return job IDs and stream progress.
3. **Staged pipeline** — Expose passes (chunk, entities, relationships, write) for progress UI and optional parallelism.
4. **Non-interactive review** — Replace TTY flows (`ontology review`, `normalize review`) with CRUD-style endpoints.
5. **Minimal new dependencies** — Prefer extending the existing Flask app or a small FastAPI module; avoid Celery until multi-worker scale is required.

## Non-goals (initial phases)

- Multi-tenant auth / RBAC
- Distributed job queue (Redis/Celery) — use in-process jobs first
- Replacing `metadata.json` with a database (optional later)

---

## Target architecture

```
┌─────────────────────────────────────────────────────────────┐
│  GUI (web / Electron / Tauri)                               │
│  - job list, progress, artifact viewers, review wizards     │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP + SSE (or WebSocket)
┌───────────────────────────▼─────────────────────────────────┐
│  src/api/          REST + SSE routes, request validation      │
│  src/services/     orchestration, job runner, progress bus    │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  src/ (existing)   DocumentProcessor, Extractors, stores, …   │
└─────────────────────────────────────────────────────────────┘
```

---

## Service layer (`src/services/`)

Extract orchestration from `main.py` into typed services. Each service returns **dataclasses / Pydantic models**, not printed strings.

| Service | Responsibility | Primary `src/` deps |
|---------|----------------|---------------------|
| `HealthService` | LLM/embed preflight (`run_precheck`) | `settings`, `httpx` |
| `PipelineService` | Full document pipeline (`process_and_extract`) | `DocumentProcessor`, extractors, `TurtleWriter`, `HTMLMarkupGenerator`, `MetadataStore`, `BenchmarkStore` |
| `DocumentService` | List/get documents, upload paths, chunk preview | `DocumentProcessor`, `MetadataStore` |
| `OntologyService` | Proposals status, approve, per-item review actions, visualize | `ProposalStore`, `OntologyManager`, `interactive_review` logic split |
| `NormalizeService` | scan / apply / per-mapping review | `predicate_normalizer`, `_review` split |
| `BenchmarkService` | show views, SQL query, clear | `BenchmarkStore` |
| `ArchiveService` | archive + reset `data/` | logic from `archive_data` |
| `ArtifactService` | Resolve paths for TTL, markup HTML, graph HTML | filesystem under `data/` |

### `PipelineService` — staged API (core refactor)

Replace the monolithic `process_and_extract` loop with explicit stages. Internal implementation can still call the same extractors.

```python
@dataclass
class PipelineOptions:
    file_path: str
    output_dir: str = "data/knowledge_graphs"
    max_chunks: int | None = None
    with_graph: bool = False
    domain: str = "default"
    skip_precheck: bool = False

@dataclass
class ChunkPlan:
    document_id: str
    filename: str
    word_count: int
    chunks: list[str]
    llm_model: str

@dataclass
class PipelineResult:
    document_id: str
    kg_path: str
    markup_path: str
    graph_path: str | None
    entity_count: int
    triple_count: int
    proposals: list[dict]

class PipelineService:
    def precheck(self) -> PrecheckResult: ...
    def plan(self, options: PipelineOptions) -> ChunkPlan: ...
    def extract_entities(self, plan: ChunkPlan, on_chunk: Callable | None = None) -> EntityPassResult: ...
    def resolve_entities(self, entities: list[dict]) -> list[dict]: ...
    def extract_relationships(self, plan: ChunkPlan, canonical_names: list[str], on_chunk: Callable | None = None) -> RelationshipPassResult: ...
    def extract_section_relationships(self, plan: ChunkPlan, canonical_names: list[str], ...) -> int: ...
    def write_outputs(self, plan: ChunkPlan, triples: list, entities: list, options: PipelineOptions) -> PipelineResult: ...
    def run(self, options: PipelineOptions, progress: ProgressReporter) -> PipelineResult:
        """Convenience: runs all stages in order (CLI default)."""
```

**Progress reporter** (injected into `run` and per-stage methods):

```python
class ProgressReporter(Protocol):
    def emit(self, event: ProgressEvent) -> None: ...

@dataclass
class ProgressEvent:
    job_id: str
    stage: Literal["precheck", "plan", "entities", "resolve", "relationships", "sections", "write", "done", "error"]
    chunk: int | None = None
    total_chunks: int | None = None
    message: str = ""
    percent: float | None = None
    payload: dict | None = None  # e.g. entity_count for chunk
```

CLI: implement `CliProgressReporter` that prints ETA lines (current behavior).  
API: implement `JobProgressReporter` that appends to an in-memory ring buffer keyed by `job_id`.

### Parallelism (Phase 3+)

Inside `extract_entities` / `extract_relationships`:

- `ThreadPoolExecutor(max_workers=config.pipeline.max_concurrent_llm_calls)` (default `1` for local Ollama).
- Collect results in chunk order; merge dedup logic unchanged.
- Guard `MetadataStore` / file writes with a module-level lock or single-writer stage after extraction.

---

## Job model

Long operations run as **background jobs** in the API process (Phase 2). Upgrade to Redis/RQ only if you need multiple API workers.

```python
@dataclass
class Job:
    id: str                          # uuid4
    type: Literal["pipeline.process", "ontology.visualize", "normalize.scan", ...]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    params: dict
    result: dict | None
    error: str | None
    progress: list[ProgressEvent]    # last N events, or separate stream
```

| Job type | Sync allowed? | Notes |
|----------|---------------|-------|
| `pipeline.process` | No | Always async + SSE |
| `health.precheck` | Yes | Fast |
| `ontology.status` | Yes | Read-only |
| `ontology.approve` | Yes | Short file merge |
| `ontology.visualize` | Optional async | Subprocess to ai-knowledge-graph |
| `normalize.scan` | Optional async | Can be slow with LLM |
| `normalize.apply` | Yes / async | Depends on KG size |
| `archive.create` | Yes | Filesystem copy |

**Cancellation**: set job flag; pipeline checks between chunks and raises `JobCancelled`.

---

## HTTP API surface

Base path: `/api/v1`  
Content-Type: `application/json`  
Errors: `{ "error": { "code": "...", "message": "..." } }`

Existing n8n routes under `/` remain during migration; new GUI uses `/api/v1` only.

**Quick test (server on port 5000):**

```bash
curl -s -X POST http://127.0.0.1:5000/api/v1/jobs/pipeline \
  -H 'Content-Type: application/json' \
  -d '{"file_path":"data/documents/my-doc.txt"}'
curl -N http://127.0.0.1:5000/api/v1/jobs/JOB_ID/events
```

### System

| Method | Path | Maps to | Sync |
|--------|------|---------|------|
| `GET` | `/health` | Liveness | Yes |
| `GET` | `/api/v1/health/precheck` | `HealthService.precheck()` | Yes |
| `GET` | `/api/v1/config` | Sanitized `load_config()` (no secrets) | Yes |

**`GET /api/v1/config` response (example):**

```json
{
  "llm": { "provider": "ollama", "model": "llama3.2", "base_url": "http://localhost:11434/v1" },
  "document": { "chunk_size": 800, "overlap": 100 },
  "entity_resolution": { "enabled": true, "strategies": ["rule_based"] },
  "domains": ["default", "technical", "literary", "scientific"]
}
```

### Documents & artifacts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/documents` | List from `MetadataStore` |
| `GET` | `/api/v1/documents/{document_id}` | Metadata + artifact paths |
| `POST` | `/api/v1/documents/upload` | Multipart → `data/documents/`; returns path |
| `POST` | `/api/v1/documents/{id}/chunk-preview` | Body: `{ "chunk_size", "overlap" }` → chunk count + first chunk sample |
| `GET` | `/api/v1/artifacts/{document_id}/kg` | Serve `.ttl` |
| `GET` | `/api/v1/artifacts/{document_id}/markup` | Serve `_markup.html` |
| `GET` | `/api/v1/artifacts/{document_id}/graph` | Serve `_graph.html` if exists |

### Pipeline (jobs)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/jobs/pipeline` | Start full pipeline → `{ "job_id" }` |
| `GET` | `/api/v1/jobs/{job_id}` | Status + result summary |
| `GET` | `/api/v1/jobs/{job_id}/events` | **SSE** stream of `ProgressEvent` |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Request cancellation |
| `GET` | `/api/v1/jobs` | List recent jobs (optional filter by status) |

**`POST /api/v1/jobs/pipeline` body:**

```json
{
  "file_path": "data/documents/my-doc.txt",
  "output_dir": "data/knowledge_graphs",
  "max_chunks": null,
  "with_graph": true,
  "domain": "default",
  "skip_precheck": false
}
```

**`GET /api/v1/jobs/{job_id}` response (succeeded):**

```json
{
  "id": "…",
  "type": "pipeline.process",
  "status": "succeeded",
  "result": {
    "document_id": "my-doc",
    "kg_path": "…",
    "markup_path": "…",
    "graph_path": "…",
    "entity_count": 42,
    "triple_count": 87,
    "proposals": [{ "label": "…", "sources": ["…"] }]
  }
}
```

**SSE event** (`GET /api/v1/jobs/{job_id}/events`):

```
event: progress
data: {"stage":"entities","chunk":3,"total_chunks":12,"message":"Entities: 8 (4.2s)","percent":25.0}

event: done
data: {"document_id":"my-doc", ...}
```

### Low-level extraction (optional; replaces n8n step API)

For power users / debugging — mirrors `src/n8n/nodes/*` but aligned with v1 paths.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/extract/document` | Chunk document only |
| `POST` | `/api/v1/extract/entities` | Body: `{ "text", "domain" }` |
| `POST` | `/api/v1/extract/relationships` | Body: `{ "text", "entities": ["…"] }` |
| `POST` | `/api/v1/extract/store` | Body: `{ "document_id", "triples", "document_metadata" }` |

Prefer **`POST /api/v1/jobs/pipeline`** for the GUI; keep granular routes for tooling.

### Ontology

| Method | Path | CLI equivalent | Notes |
|--------|------|----------------|-------|
| `GET` | `/api/v1/ontology/status` | `ontology status` | Summary + pending list |
| `GET` | `/api/v1/ontology/proposals` | — | Paginated pending / needs_typing |
| `GET` | `/api/v1/ontology/proposals/{uri}` | — | Single proposal detail |
| `PATCH` | `/api/v1/ontology/proposals/{uri}` | Part of `ontology review` | `{ "status": "approved" \| "rejected", "parent_class_uri": "…", "wikidata_id": "…" }` |
| `POST` | `/api/v1/ontology/proposals/{uri}/suggest-placement` | LLM + Wikidata step | Returns ranked parent classes |
| `POST` | `/api/v1/ontology/approve` | `ontology approve` | Bulk merge approved → `ontology.ttl` |
| `POST` | `/api/v1/jobs/ontology/visualize` | `ontology visualize` | Async; artifact at `data/documents/ontology_graph.html` |

### Predicate normalization

| Method | Path | CLI equivalent |
|--------|------|----------------|
| `GET` | `/api/v1/normalize/map` | Read `predicate_map.yaml` |
| `POST` | `/api/v1/jobs/normalize/scan` | `normalize scan` |
| `PATCH` | `/api/v1/normalize/map/groups/{canonical}` | Set `reviewed`, edit canonical |
| `POST` | `/api/v1/normalize/apply` | `normalize apply` — body: `{ "dry_run": false }` |

Replace `normalize review` TTY loop with **PATCH per mapping group** in the GUI.

### Benchmark

| Method | Path | CLI equivalent |
|--------|------|----------------|
| `GET` | `/api/v1/benchmark/runs` | `benchmark show runs` |
| `GET` | `/api/v1/benchmark/chunks` | `benchmark show chunks` |
| `GET` | `/api/v1/benchmark/llm` | `benchmark show llm` |
| `POST` | `/api/v1/benchmark/query` | `benchmark query` — body: `{ "sql": "SELECT …" }` (read-only SQL validation) |
| `DELETE` | `/api/v1/benchmark` | `benchmark clear` |

Return JSON tables `{ "columns": [...], "rows": [[...]] }` instead of pretty-printed text.

### Archive

| Method | Path | CLI equivalent |
|--------|------|----------------|
| `POST` | `/api/v1/archive` | `archive` — body: `{ "name": null, "llmnamed": false }` |

---

## CLI → service mapping

| CLI | Service method / job |
|-----|-------------------|
| `process` | `PipelineService.run` → job `pipeline.process` |
| *(implicit)* | `HealthService.precheck` before process |
| `server` | Run `src/api/app.py` (Flask/FastAPI) |
| `archive` | `ArchiveService.create` |
| `ontology status` | `OntologyService.status` |
| `ontology approve` | `OntologyService.approve_all` |
| `ontology review` | GUI: `GET/PATCH` proposals + `suggest-placement` |
| `ontology visualize` | `OntologyService.visualize` (job) |
| `normalize scan` | `NormalizeService.scan` (job) |
| `normalize review` | `NormalizeService.update_mapping` (per group) |
| `normalize apply` | `NormalizeService.apply` |
| `benchmark show` | `BenchmarkService.get_view` |
| `benchmark query` | `BenchmarkService.query` |
| `benchmark clear` | `BenchmarkService.clear` |

`main.py` after refactor (~30 lines per command):

```python
def main():
    args = parse_args()
    if args.command == "process":
        svc = PipelineService()
        if not args.skip_precheck and not HealthService().precheck().ok:
            sys.exit(1)
        result = svc.run(PipelineOptions(...), CliProgressReporter())
        print_summary(result)
```

---

## Phased execution plan

### Phase 0 — Document & contracts (1–2 days)

- [x] This document (`docs/GUI_API_PLAN.md`)
- [ ] Agree on `/api/v1` paths and job model with stakeholders
- [ ] Add OpenAPI stub (`docs/openapi.yaml`) generated from route table (optional)

### Phase 1 — Service extraction (3–5 days)

**Goal:** CLI behavior unchanged; logic moves out of `main.py`.

1. Create `src/services/` with `HealthService`, `PipelineService` (initially wrap `process_and_extract` as single `run()`).
2. Introduce `ProgressReporter` protocol; adapt existing `print` statements in pipeline to `progress.emit(...)`.
3. Return structured `PipelineResult` everywhere (already partially done).
4. Thin `main.py` to call services.
5. **Tests:** run existing `test/` suite; add one service-level test with mocked LLM.

**Exit criteria:** `uv run python main.py process …` identical output; no new HTTP routes yet.

### Phase 2 — Job runner + API v1 core (4–6 days)

**Goal:** GUI can drive full pipeline with progress.

1. `src/services/jobs.py` — in-memory `JobStore`, background thread per job.
2. `src/api/` — Flask blueprint or FastAPI router under `/api/v1`.
3. Endpoints: `health`, `config`, `jobs/pipeline`, `jobs/{id}`, `jobs/{id}/events` (SSE).
4. Wire `PipelineService.run(..., JobProgressReporter(job_id))`.
5. Document + artifact list/get routes (read-only).
6. Deprecation note in README for raw n8n `/process` (keep working).

**Exit criteria:** `curl` can start pipeline and stream SSE; CLI still works.

### Phase 3 — Staged pipeline + parallelism (5–8 days)

**Goal:** Faster runs; finer progress in GUI.

1. Split `PipelineService` into `plan`, `extract_entities`, `resolve_entities`, `extract_relationships`, `write_outputs`.
2. Add `max_concurrent_llm_calls` to `config.yaml` (default `1`).
3. Parallel chunk extraction with ordered merge.
4. Optional: `POST /api/v1/jobs/pipeline` query param `?stage=entities` for stepwise debugging (advanced).

**Exit criteria:** Benchmark shows reduced wall time for multi-chunk docs when concurrency > 1 and provider allows it.

### Phase 4 — Ontology & normalize GUI APIs (4–5 days)

**Goal:** No terminal required for review workflows.

1. `OntologyService` — expose `ProposalStore` operations as REST resources.
2. Extract non-interactive helpers from `interactive_review.py` (Wikidata fetch, placement suggest).
3. `NormalizeService` — YAML read/write + `apply` / `scan` jobs.
4. Endpoints per tables above.

**Exit criteria:** Approve/reject proposals and predicate mappings via HTTP only.

### Phase 5 — GUI shell (parallel track; 2–4 weeks)

**Goal:** Usable desktop or web UI.

Suggested stack (pick one):

- **Web:** Vite + React (or Svelte) talking to local API; embed graph/markup via iframe or static file URLs.
- **Desktop:** Tauri wrapping the same web UI; spawn API subprocess on launch.

**Minimum screens:**

1. Dashboard — precheck status, recent jobs, document list  
2. Process — file picker, domain/options, live progress, links to artifacts  
3. Ontology — proposal queue, approve/reject, Wikidata hints  
4. Normalize — mapping table editor, scan/apply  
5. Benchmark — tables + simple charts  

**Exit criteria:** Full happy path without CLI.

### Phase 6 — Hardening (ongoing)

- File locking / single-writer for `metadata.json`
- Job persistence (SQLite job table) if API restarts must not lose state
- OpenAPI + generated TypeScript client for GUI
- Auth (local token) if API binds beyond localhost

---

## OpenAPI type sketch (shared models)

Authoritative field-level reference (including untyped domain dicts and CLI/GUI mirrors): [INFOMODEL.md](./INFOMODEL.md).

```yaml
components:
  schemas:
    Job:
      type: object
      properties:
        id: { type: string, format: uuid }
        type: { type: string }
        status: { enum: [queued, running, succeeded, failed, cancelled] }
        result: { type: object, nullable: true }
        error: { type: string, nullable: true }
    ProgressEvent:
      type: object
      properties:
        stage: { type: string }
        chunk: { type: integer, nullable: true }
        total_chunks: { type: integer, nullable: true }
        message: { type: string }
        percent: { type: number, nullable: true }
    PipelineRequest:
      type: object
      required: [file_path]
      properties:
        file_path: { type: string }
        output_dir: { type: string, default: data/knowledge_graphs }
        max_chunks: { type: integer, nullable: true }
        with_graph: { type: boolean, default: false }
        domain: { type: string, default: default }
    PipelineResult:
      type: object
      properties:
        document_id: { type: string }
        kg_path: { type: string }
        markup_path: { type: string }
        graph_path: { type: string, nullable: true }
        entity_count: { type: integer }
        triple_count: { type: integer }
        proposals: { type: array, items: { type: object } }
```

---

## Migration from existing n8n server

| Legacy (`src/n8n/server.py`) | v1 replacement |
|------------------------------|----------------|
| `GET /health` | `GET /health` (unchanged) |
| `POST /process` | `POST /api/v1/jobs/pipeline` |
| `POST /extract/entities` | `POST /api/v1/extract/entities` |
| `POST /extract/relationships` | `POST /api/v1/extract/relationships` |
| `POST /store` | `POST /api/v1/extract/store` |
| `GET /metadata`, `GET /metadata/:id` | `GET /api/v1/documents`, `GET /api/v1/documents/:id` |

Keep legacy routes as thin proxies to v1 services for one release, then remove.

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| LLM overload from parallel chunks | Configurable concurrency; default 1 |
| `metadata.json` corruption | Single-writer stage; file lock in Phase 6 |
| Interactive review logic tightly coupled to stdin | Split `interactive_review` into pure functions + service |
| Large SSE buffers | Ring buffer per job (e.g. last 200 events) |
| Subprocess graph generation | Run in job thread; surface stderr in `job.error` |

---

## Suggested directory layout (end state)

```
src/
  api/
    __init__.py
    app.py              # create_app(), register blueprints
    routes/
      health.py
      jobs.py
      documents.py
      ontology.py
      normalize.py
      benchmark.py
      archive.py
    sse.py              # EventSource helpers
  services/
    __init__.py
    health.py
    pipeline.py
    documents.py
    ontology.py
    normalize.py
    benchmark.py
    archive.py
    artifacts.py
    jobs.py             # JobStore, runner
    progress.py         # ProgressEvent, reporters
main.py                 # CLI only
```

---

## Summary

- **Do not** build the GUI on CLI subprocesses; **do** extract `src/services/` from `main.py` and expose **`/api/v1`** with **jobs + SSE** for `process`.
- Commands are already Python-callable; the work is **decomposing the pipeline**, **progress events**, and **REST resources** for review flows.
- Parallelism is a **service-layer** concern (chunk pools), controlled by config, not by the GUI firing multiple CLI processes.
