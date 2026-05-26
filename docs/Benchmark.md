# Pipeline Benchmarking

The benchmark module records detailed metrics for every pipeline run to a local [DuckDB](https://duckdb.org) database (`data/benchmark.duckdb`). DuckDB is embedded — no server required.

---

## Installation

Benchmarking is an optional dependency:

```bash
# With benchmarking
uv sync --extra benchmark

# Without (pipeline works unchanged; all recording is a no-op)
uv sync
```

---

## Data model

Five tables in 3NF. `run_id` (UUID) is the primary key for a pipeline invocation and the foreign key linking all other tables.

```
runs ──< run_strategies
     ──< chunks
     ──< llm_calls
     ──< resolution_runs
```

### `runs` — one row per pipeline invocation

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT PK | UUID assigned at pipeline start |
| `started_at` | TIMESTAMP | UTC timestamp when processing began |
| `finished_at` | TIMESTAMP | UTC timestamp when pipeline completed |
| `document_filename` | TEXT | Base filename of the input document |
| `document_id` | TEXT | SHA-256 hash of the document file |
| `word_count` | INTEGER | Total words in the document |
| `chunk_count` | INTEGER | Number of chunks actually processed |
| `max_chunks` | INTEGER | `--max-chunks` limit (NULL = no limit) |
| `entities_raw` | INTEGER | Entities after extraction and dedup |
| `entities_resolved` | INTEGER | Entities after resolution pass |
| `triples` | INTEGER | Unique relationship triples extracted |
| `elapsed_s` | DOUBLE | Total wall-clock seconds for the run |
| `llm_provider` | TEXT | Provider name (lmstudio, openai, …) |
| `llm_model` | TEXT | Model identifier |
| `resolution_enabled` | BOOLEAN | Whether entity resolution ran |
| `proposals` | INTEGER | New ontology classes proposed |

### `run_strategies` — resolution strategies (normalized)

One row per strategy per run, in execution order.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT FK | References `runs.run_id` |
| `position` | INTEGER | Execution order (0-based) |
| `strategy` | TEXT | `rule_based` \| `embedding` \| `llm` |

### `chunks` — per-chunk extraction metrics

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT FK | References `runs.run_id` |
| `chunk_number` | INTEGER | 1-based chunk index |
| `word_count` | INTEGER | Words in this chunk |
| `entities` | INTEGER | Entities extracted from this chunk |
| `relationships` | INTEGER | Relationships extracted from this chunk |
| `elapsed_s` | DOUBLE | Wall-clock seconds for both LLM calls |

### `llm_calls` — individual LLM call timings

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT FK | References `runs.run_id` |
| `chunk_number` | INTEGER | Chunk this call belongs to (0 = resolution) |
| `stage` | TEXT | `entity_extraction` \| `relationship_extraction` \| `resolution_*` |
| `elapsed_s` | DOUBLE | Wall-clock seconds for the HTTP call |
| `tokens_in_approx` | INTEGER | Approximate input tokens (0 if not measured) |
| `tokens_out_approx` | INTEGER | Approximate output tokens (0 if not measured) |

### `resolution_runs` — entity resolution metrics

Note: `merges` is not stored — compute as `entities_before - entities_after`.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT FK | References `runs.run_id` |
| `strategy` | TEXT | Strategy combination used |
| `entities_before` | INTEGER | Entity count entering the resolver |
| `entities_after` | INTEGER | Entity count after merging |
| `elapsed_s` | DOUBLE | Seconds spent in resolution |

---

## CLI

```bash
# Summary table — last 20 runs
uv run python main.py benchmark show

# Per-chunk timing breakdown
uv run python main.py benchmark show chunks

# Per-LLM-call timings
uv run python main.py benchmark show llm

# Arbitrary SQL
uv run python main.py benchmark query "<sql>"

# Clear all data
uv run python main.py benchmark clear
```

---

## Example queries

**Average run time by model:**
```sql
SELECT llm_model, round(avg(elapsed_s), 1) AS avg_s, count(*) AS runs
FROM runs
GROUP BY llm_model
ORDER BY avg_s;
```

**Entity extraction rate by document:**
```sql
SELECT document_filename,
       sum(entities)      AS total_entities,
       sum(relationships) AS total_rels,
       round(sum(elapsed_s), 1) AS total_s
FROM chunks c JOIN runs r USING (run_id)
GROUP BY document_filename;
```

**Resolution effectiveness:**
```sql
SELECT r.document_filename,
       rr.strategy,
       rr.entities_before,
       rr.entities_after,
       rr.entities_before - rr.entities_after AS merges,
       round(rr.elapsed_s, 2) AS elapsed_s
FROM resolution_runs rr
JOIN runs r USING (run_id)
ORDER BY r.started_at DESC;
```

**Slowest LLM calls:**
```sql
SELECT r.document_filename, l.stage, l.chunk_number, round(l.elapsed_s, 1) AS elapsed_s
FROM llm_calls l
JOIN runs r USING (run_id)
ORDER BY l.elapsed_s DESC
LIMIT 10;
```

**Strategies used per run:**
```sql
SELECT r.document_filename, string_agg(s.strategy, '→' ORDER BY s.position) AS strategies
FROM runs r
JOIN run_strategies s USING (run_id)
GROUP BY r.run_id, r.document_filename;
```

---

## Direct DuckDB access

The database file is at `data/benchmark.duckdb`. You can open it directly with:

```bash
# DuckDB CLI (if installed separately)
duckdb data/benchmark.duckdb

# Or from Python
import duckdb
con = duckdb.connect("data/benchmark.duckdb")
con.sql("SELECT * FROM runs").show()
```

The file is gitignored and never committed.
