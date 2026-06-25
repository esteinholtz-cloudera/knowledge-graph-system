# GUI / API — Implementation Plan

Actionable build plan derived from [GUI_API_PLAN.md](./GUI_API_PLAN.md). Use ticket IDs (`KG-###`) in commits and PRs.

**Scope:** Ingestion bounded context only (repo root). Reasoning design lives under [`reasoning/`](../reasoning/) — see [CONTEXT-MAP.md](../CONTEXT-MAP.md).

**Prerequisites:** Python 3.8+, `uv sync`, existing tests green (`uv run pytest`).

**Dependency policy:** No Celery/Redis in Phases 1–4. Reuse Flask + Pydantic already in `pyproject.toml`.

---

## Overview

| Phase | Outcome | Est. | Blocks GUI? |
|-------|---------|------|-------------|
| 1 | Service layer; CLI unchanged | 3–5 d | Yes |
| 2 | Jobs + `/api/v1` pipeline + SSE | 4–6 d | Partial |
| 3 | Staged pipeline + parallel chunks | 5–8 d | No |
| 4 | Ontology + normalize REST | 4–5 d | Partial |
| 5 | GUI application | 2–4 w | — |
| 6 | Hardening | ongoing | — |

**Critical path:** 1.1 → 1.4 → 1.6 → 2.1 → 2.3 → 2.5 → 5.x

---

## Dependency graph (phases)

```
Phase 1 (services)
  KG-101 models/progress
  KG-102 health
  KG-103 pipeline move
  KG-104 other services
  KG-105 thin main.py
  KG-106 tests
       │
       ▼
Phase 2 (API + jobs)
  KG-201 job store
  KG-202 progress bus
  KG-203 api app
  KG-204 pipeline routes + SSE
  KG-205 documents/artifacts
  KG-206 legacy proxy
       │
       ├──────────────────┐
       ▼                  ▼
Phase 3 (staged)    Phase 4 (review APIs)
  KG-301 split        KG-401 ontology
  KG-302 parallel     KG-402 normalize
  KG-303 config       KG-403 benchmark/archive
       │                  │
       └────────┬─────────┘
                ▼
         Phase 5 (GUI)
         Phase 6 (hardening)
```

---

## Phase 1 — Service extraction

**Goal:** All CLI behavior lives in `src/services/`; `main.py` < 150 lines of dispatch + printing.

### KG-101 — Shared models and progress protocol

**Create**

| File | Purpose |
|------|---------|
| `src/services/__init__.py` | Public exports |
| `src/services/models.py` | Dataclasses: `PrecheckResult`, `PipelineOptions`, `PipelineResult`, `ChunkPlan`, etc. |
| `src/services/progress.py` | `ProgressEvent`, `ProgressReporter` protocol, `NullProgressReporter`, `CliProgressReporter` |

**`ProgressEvent` fields**

```python
job_id: str = ""           # empty for CLI
stage: str                 # precheck | plan | entities | resolve | relationships | sections | write | done | error
chunk: int | None = None
total_chunks: int | None = None
message: str = ""
percent: float | None = None
payload: dict | None = None
```

**`CliProgressReporter`**

- Map `emit()` to existing `print()` patterns (chunk headers, ETA, pass banners).
- Preserve current UX; do not change message text in Phase 1 unless tests break.

**DoD**

- [ ] Unit test: `CliProgressReporter` emits expected stages for a mocked 2-chunk run (no LLM).

**Est:** 0.5 d

---

### KG-102 — `HealthService`

**Create:** `src/services/health.py`

**Move from `main.py`:** `run_precheck()` → `HealthService.check() -> PrecheckResult`

- `PrecheckResult.ok: bool`, `checks: list[dict]` (llm, embed, resolution summary).
- No `print()` inside service; CLI prints from `checks`.

**Modify:** `main.py` — call `HealthService().check()`; print summary; `sys.exit(1)` if not `ok`.

**DoD**

- [ ] `uv run python main.py process …` still fails fast when LLM unreachable (manual or mocked httpx).

**Est:** 0.5 d

---

### KG-103 — `PipelineService` (monolithic first)

**Create:** `src/services/pipeline.py`

**Move from `main.py`:**

- `process_and_extract` → `PipelineService.run(options, reporter) -> PipelineResult`
- `generate_graph_html` → `PipelineService._generate_graph_html` or `ArtifactService.generate_graph_from_ttl`

**Constructor dependencies (inject for tests):**

```python
class PipelineService:
    def __init__(
        self,
        project_root: Path | None = None,
        entity_extractor_factory=EntityExtractor,
        ...
    ): ...
```

**Keep in `main.py` temporarily (re-export or delegate):**

- Nothing from pipeline body — only `process` command handler.

**Internal structure (single `run()` method initially):**

1. Copy `process_and_extract` body verbatim into `run()`.
2. Replace every progress `print` with `reporter.emit(ProgressEvent(...))`.
3. Return `PipelineResult` (already dict-like today → dataclass).

**DoD**

- [ ] Full pipeline on a small fixture doc produces same TTL/markup paths as before.
- [ ] No functional change to benchmark recording.

**Est:** 1.5 d

---

### KG-104 — Remaining services

**Create**

| File | Source in `main.py` |
|------|---------------------|
| `src/services/benchmark.py` | `show_benchmark`, `clear_benchmark` |
| `src/services/archive.py` | `archive_data` |
| `src/services/ontology.py` | `show_ontology_status`, `approve_ontology`, `visualize_ontology`, `run_ontology_review` (delegate to existing interactive for now) |
| `src/services/normalize.py` | `run_normalize`, `_regenerate_graphs` |
| `src/services/artifacts.py` | Path resolution for kg/markup/graph; `generate_graph_html` if not on pipeline |

**Return types**

- Benchmark: `TableResult(columns, rows)` not printed tables.
- Ontology status: `OntologyStatusResult` with counts + pending list.
- Archive: `ArchiveResult(archive_path, paths_updated)`.

**DoD**

- [ ] Each CLI subcommand works via service call.

**Est:** 1 d

---

### KG-105 — Thin `main.py`

**Target `main.py` responsibilities only:**

- `argparse` setup
- Dispatch to services
- Human-readable `print()` / `sys.exit()` for CLI
- `if __name__ == "__main__"`

**Remove:** All business logic blocks (should be ~900 lines → ~120 lines).

**DoD**

- [ ] `main.py` line count < 200.
- [ ] `uv run pytest` all green.

**Est:** 0.5 d

---

### KG-106 — Phase 1 tests

**Create**

| File | Tests |
|------|-------|
| `test/test_services_health.py` | Mock httpx; `PrecheckResult.ok` true/false |
| `test/test_services_pipeline.py` | Mock `LLMClient.generate`; 1 chunk; assert `PipelineResult` fields |
| `test/test_services_progress.py` | Collect events from reporter |

**DoD**

- [ ] CI-equivalent: `uv run pytest test/test_services_*.py`

**Est:** 1 d

---

### Phase 1 PR checklist

- [ ] No new runtime dependencies
- [ ] README: one line pointing to services (optional)
- [ ] Backward compatible CLI flags

**Phase 1 total:** ~5 d

---

## Phase 2 — Jobs and HTTP API

**Goal:** Start pipeline via HTTP; stream progress via SSE; list documents/artifacts.

### KG-201 — Job store and runner

**Create:** `src/services/jobs.py`

```python
class JobStore:
    def create(self, job_type: str, params: dict) -> Job: ...
    def get(self, job_id: str) -> Job | None: ...
    def list(self, status: str | None = None, limit: int = 50) -> list[Job]: ...
    def update_status(self, job_id, status, result=None, error=None): ...
    def append_event(self, job_id, event: ProgressEvent): ...
    def get_events(self, job_id, since_index: int = 0) -> list[ProgressEvent]: ...

class JobRunner:
    def submit(self, fn: Callable, job_id: str): ...  # threading.Thread
```

- In-memory dict + `threading.Lock`.
- Ring buffer: max 500 events per job.
- `JobCancelled` exception checked between pipeline chunks (wire in KG-203).

**DoD**

- [ ] Unit test: job transitions queued → running → succeeded; events appended.

**Est:** 1 d

---

### KG-202 — `JobProgressReporter`

**Create:** in `src/services/progress.py`

- `emit()` → `JobStore.append_event(job_id, event)`.
- Set `event.job_id`.

**DoD**

- [ ] Pipeline run via runner produces retrievable events.

**Est:** 0.25 d

---

### KG-203 — API application skeleton

**Create**

```
src/api/
  __init__.py
  app.py              # create_app() -> Flask
  errors.py           # register_error_handlers
  routes/
    __init__.py
    health.py
    config.py
    jobs.py
    documents.py
  sse.py              # flask Response generator for text/event-stream
```

**`app.py`**

```python
def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(health_bp, url_prefix="/api/v1")
    ...
    # Legacy n8n routes: import and register at "/" from src.n8n.server (KG-206)
    return app
```

**CLI entry:** `main.py server` → `create_app().run(...)` instead of `src.n8n.server.app` directly.

**DoD**

- [ ] `GET /api/v1/health/precheck` returns JSON.
- [ ] `GET /api/v1/config` returns sanitized config (no env var values).

**Est:** 1 d

---

### KG-204 — Pipeline job routes + SSE

**Create:** `src/api/routes/jobs.py`

| Route | Implementation |
|-------|----------------|
| `POST /api/v1/jobs/pipeline` | Validate body (Pydantic `PipelineRequest`); `JobStore.create`; `JobRunner.submit(pipeline_service.run, ...)` |
| `GET /api/v1/jobs/<id>` | `Job` JSON |
| `GET /api/v1/jobs/<id>/events` | SSE: poll `get_events(since_index)` every 0.5s until terminal status |
| `POST /api/v1/jobs/<id>/cancel` | Set cancel flag on job |
| `GET /api/v1/jobs` | List recent |

**Pydantic models:** `src/api/schemas.py` (or colocate in routes)

**PipelineService change:** Accept optional `cancel_check: Callable[[], bool]` between chunks.

**DoD**

- [ ] `curl -N` on events stream shows entity/relationship progress.
- [ ] Completed job returns same `PipelineResult` as CLI.

**Est:** 1.5 d

---

### KG-205 — Documents and artifacts routes

**Create:** `src/api/routes/documents.py`

| Route | Service |
|-------|---------|
| `GET /api/v1/documents` | `MetadataStore.list_documents()` enriched |
| `GET /api/v1/documents/<id>` | `MetadataStore.get_document()` |
| `POST /api/v1/documents/upload` | Save to `data/documents/`; validate extension |
| `GET /api/v1/artifacts/<id>/kg` | `send_file` with path validation (under `data/`) |

**Create:** `src/services/documents.py` — thin wrapper over `MetadataStore` + upload helper.

**Security:** Reject path traversal in `file_path` and artifact paths (`..`, absolute paths outside project root).

**DoD**

- [ ] After CLI process, `GET documents` lists doc; `GET artifacts/.../kg` returns TTL.

**Est:** 1 d

---

### KG-206 — Legacy n8n proxy

**Modify:** `src/n8n/server.py` — routes call services OR register as deprecated wrappers in `create_app()`.

| Legacy | Proxy to |
|--------|----------|
| `POST /process` | `POST /api/v1/jobs/pipeline` (sync wait optional — document as deprecated) |
| `POST /extract/*` | Phase 2b optional (KG-207) |
| `GET /metadata*` | `/api/v1/documents` |

**DoD**

- [ ] Existing n8n workflows still work OR README migration note.

**Est:** 0.5 d

---

### KG-207 (optional) — Granular extract routes

**Create:** `src/api/routes/extract.py`

- Delegate to `src/n8n/nodes/*` or move node logic into services.

**Est:** 0.5 d — defer if not needed for first GUI milestone.

---

### KG-208 — Phase 2 tests

**Create:** `test/test_api_jobs.py` using Flask test client

- Start job with mocked pipeline (patch `PipelineService.run`).
- Assert SSE contains `stage=done`.
- Assert 400 on missing `file_path`.

**Est:** 1 d

---

### Phase 2 PR checklist

- [ ] Update README CLI section: `server` serves `/api/v1`
- [ ] Example `curl` for pipeline + SSE in `docs/GUI_API_PLAN.md` or README

**Phase 2 total:** ~6 d

---

## Phase 3 — Staged pipeline and parallelism

**Goal:** `PipelineService` split into stages; optional concurrent chunk LLM calls.

### KG-301 — Split `PipelineService.run()`

**Refactor `src/services/pipeline.py`:**

| Method | Extracted from |
|--------|----------------|
| `_build_plan(options) -> ChunkPlan` | DocumentProcessor + chunk limit |
| `_extract_entities(plan, reporter) -> EntityPassResult` | Pass 1 loop + dedup |
| `_resolve_entities(entities) -> list` | EntityResolver block |
| `_extract_relationships(plan, names, reporter) -> list` | Pass 2 + 2b |
| `_write_outputs(plan, triples, entities, options) -> PipelineResult` | TTL, markup, graph, metadata, benchmark finish |

`run()` calls stages in order (same as today).

**DoD**

- [ ] Each stage emits distinct `ProgressEvent.stage`.
- [ ] Existing tests still pass.

**Est:** 2 d

---

### KG-302 — Parallel chunk extraction

**Modify:** `config/config.yaml` + `settings.py`:

```yaml
pipeline:
  max_concurrent_llm_calls: 1   # increase for cloud APIs
```

**Implement:** `concurrent.futures.ThreadPoolExecutor` in `_extract_entities` and relationship pass.

- Submit all chunks; collect in **chunk index order** before merge.
- Shared `BenchmarkStore.record_llm_call` — thread-safe or record in main thread after each future completes.

**DoD**

- [ ] With `max_concurrent_llm_calls: 2` and mocked slow LLM, wall time < 2× single chunk (unit test with sleep mocks).

**Est:** 2 d

---

### KG-303 — Cancel between stages

- Check `cancel_check()` at start of each stage and each chunk batch.
- API: cancelled job → `status=cancelled`, partial events preserved.

**Est:** 0.5 d

---

### Phase 3 total:** ~5 d

---

## Phase 4 — Review and admin APIs

### KG-401 — Ontology REST (non-interactive)

**Extend:** `src/services/ontology.py`

| Method | Logic source |
|--------|--------------|
| `status()` | `ProposalStore.status_summary()` |
| `list_proposals(filter)` | `get_pending`, `get_needs_typing` |
| `get_proposal(uri)` | `get_all` filter |
| `update_proposal(uri, body)` | Set review status, parent class — extract from `interactive_review.py` |
| `suggest_placement(uri)` | `_wikidata_search`, placement proposer |
| `approve_all()` | `OntologyManager.approve_proposed_ontology()` |

**Refactor:** `src/ontology/interactive_review.py`

- Extract pure functions: `search_wikidata`, `suggest_parents`, `apply_proposal_decision` (no `input()`).
- `run_interactive_review` becomes thin TTY loop calling those functions.

**Create:** `src/api/routes/ontology.py` — routes per GUI_API_PLAN.md.

**Est:** 2.5 d

---

### KG-402 — Normalize REST

**Extend:** `src/services/normalize.py`

| Method | Notes |
|--------|-------|
| `get_map()` | Read YAML → dict |
| `update_group(canonical, body)` | Set `reviewed`, edit variants |
| `scan(...)` | Job or sync; returns map stats |
| `apply(dry_run)` | Existing `apply_predicate_map` |

**Refactor:** `src/normalization/_review.py` — keep `interactive_review` for CLI; add `review_group_cli` vs service `update_group`.

**Create:** `src/api/routes/normalize.py`

**Est:** 1.5 d

---

### KG-403 — Benchmark and archive routes

**Create:** `src/api/routes/benchmark.py`, `src/api/routes/archive.py`

- Benchmark query: allow only `SELECT` (strip comments; reject `;` multi-statement).
- Archive: `POST /api/v1/archive` sync.

**Est:** 1 d

---

### KG-404 — Phase 4 tests

- Ontology: patch `ProposalStore`; PATCH proposal → status in TTL file.
- Normalize: temp kg dir + apply dry_run.

**Est:** 1 d

---

### Phase 4 total:** ~6 d

---

## Phase 5 — GUI application

**Separate repo or `gui/` folder** — team choice. Plan assumes `gui/` in same monorepo.

### KG-501 — Project scaffold

- Vite + React + TypeScript (or Svelte).
- `VITE_API_BASE=http://127.0.0.1:5000/api/v1`
- Generated types from OpenAPI (KG-601 optional).

**Est:** 1 d

---

### KG-502 — API client module

**Create:** `gui/src/api/client.ts`

- `startPipeline(body)`, `getJob(id)`, `subscribeJobEvents(id, onEvent)` (EventSource).
- `getDocuments()`, `getPrecheck()`, `getConfig()`.

**Est:** 1 d

---

### KG-503 — Dashboard screen

- Precheck status (green/red).
- Recent jobs table (poll `GET /jobs` every 5s).
- Document list with links to artifacts.

**Est:** 2 d

---

### KG-504 — Process screen

- File picker → upload → start job.
- Options: domain, max_chunks, with_graph.
- Live progress bar from SSE (`percent` or chunk/total).
- On done: links to markup, graph, download TTL.

**Est:** 3 d

---

### KG-505 — Ontology review screen

- Table of pending proposals.
- Side panel: Wikidata suggestions, approve/reject, parent class picker.
- Bulk approve button.

**Est:** 3 d

---

### KG-506 — Normalize screen

- Load predicate map.
- Editable table: canonical, variants, reviewed checkbox.
- Scan (job) + Apply (dry-run toggle).

**Est:** 2 d

---

### KG-507 — Benchmark screen

- Tabs: runs / chunks / llm (tables from API).
- Optional: simple bar chart (no heavy chart lib required).

**Est:** 1 d

---

### KG-508 — Desktop wrapper (optional)

- Tauri: spawn `uv run python main.py server` on app start; shutdown on exit.

**Est:** 2 d

---

### Phase 5 total:** ~15 d (3 weeks)

---

## Phase 6 — Hardening (backlog)

| Ticket | Task |
|--------|------|
| KG-601 | `docs/openapi.yaml` + export script |
| KG-602 | SQLite `jobs.db` persistence (survive API restart) |
| KG-603 | `fcntl` / file lock on `metadata.json` writes |
| KG-604 | Localhost-only bind default; optional API token header |
| KG-605 | Rate limit on `benchmark/query` |

---

## File creation summary (Phases 1–4)

```
src/services/
  __init__.py
  models.py
  progress.py
  health.py
  pipeline.py
  documents.py
  artifacts.py
  ontology.py
  normalize.py
  benchmark.py
  archive.py
  jobs.py

src/api/
  __init__.py
  app.py
  errors.py
  schemas.py
  sse.py
  routes/
    health.py
    config.py
    jobs.py
    documents.py
    ontology.py      # Phase 4
    normalize.py     # Phase 4
    benchmark.py     # Phase 4
    archive.py       # Phase 4
    extract.py       # optional Phase 2

test/
  test_services_health.py
  test_services_pipeline.py
  test_services_progress.py
  test_api_jobs.py
  test_api_ontology.py   # Phase 4
```

**Modified:** `main.py`, `config/config.yaml`, `src/config/settings.py`, `src/n8n/server.py`, `src/ontology/interactive_review.py`, `README.md`

---

## Suggested implementation order (single developer)

| Week | Tickets | Deliverable |
|------|---------|-------------|
| 1 | KG-101 → KG-105 | Services + thin CLI |
| 1 | KG-106 | Service tests |
| 2 | KG-201 → KG-205 | API + SSE + documents |
| 2 | KG-206, KG-208 | Legacy proxy + API tests |
| 3 | KG-301 → KG-303 | Staged + parallel pipeline |
| 4 | KG-401 → KG-404 | Ontology/normalize/admin API |
| 5–7 | KG-501 → KG-507 | GUI screens |
| 8+ | KG-508, KG-601+ | Tauri, OpenAPI, hardening |

---

## Acceptance criteria (MVP for GUI)

The MVP is done when a user can **without the terminal**:

1. Upload a document and start processing.
2. See live progress until completion.
3. Open markup and graph artifacts in the browser.
4. Review and approve ontology proposals.
5. Run normalize scan, edit map, apply.

CLI commands remain available for scripting and CI.

---

## Risk register (implementation-specific)

| Risk | Mitigation | Ticket |
|------|------------|--------|
| `process_and_extract` move introduces subtle bug | Phase 1: move verbatim first; diff TTL output on fixture doc | KG-103 |
| SSE proxies buffer in nginx | Document dev uses Flask directly; prod note in README | KG-204 |
| Interactive review refactor breaks CLI | Keep `run_interactive_review` calling new pure functions | KG-401 |
| Parallel LLM breaks Ollama | Default `max_concurrent_llm_calls: 1` | KG-302 |
| Pydantic v2 on Python 3.8 | Already in deps; use `model_validate` | KG-203 |

---

## Related documents

- [INFOMODEL.md](./INFOMODEL.md) — internal information model, API mapping, change checklist
- [GUI_API_PLAN.md](./GUI_API_PLAN.md) — architecture, endpoint catalog, data models
- [README.md](../README.md) — user-facing CLI (update after Phase 2)
