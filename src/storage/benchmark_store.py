"""
Benchmark storage using DuckDB (embedded, no server required).

DuckDB is an optional dependency. If not installed, BenchmarkStore falls back
to NullBenchmarkStore which silently no-ops all calls so the pipeline keeps
running unchanged.

Install the benchmark extra to enable:
    uv sync --extra benchmark

Schema
------
runs          — one row per pipeline invocation
chunks        — one row per chunk per run
llm_calls     — one row per LLM API call
resolution    — one row per resolution strategy per run
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _DUCKDB_AVAILABLE = False


_DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "benchmark.duckdb")

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    started_at        TIMESTAMP,
    finished_at       TIMESTAMP,
    document_filename TEXT,
    document_id       TEXT,
    word_count        INTEGER,
    chunk_count       INTEGER,
    max_chunks        INTEGER,
    entities_raw      INTEGER,
    entities_resolved INTEGER,
    triples           INTEGER,
    elapsed_s         DOUBLE,
    llm_provider      TEXT,
    llm_model         TEXT,
    resolution_enabled BOOLEAN,
    proposals         INTEGER
);

-- Normalized: one row per strategy per run (replaces CSV in runs.resolution_strategies)
CREATE TABLE IF NOT EXISTS run_strategies (
    run_id    TEXT,
    position  INTEGER,   -- preserves execution order
    strategy  TEXT,
    PRIMARY KEY (run_id, position)
);

CREATE TABLE IF NOT EXISTS chunks (
    id                INTEGER,
    run_id            TEXT,
    chunk_number      INTEGER,
    word_count        INTEGER,
    entities          INTEGER,
    relationships     INTEGER,
    elapsed_s         DOUBLE,
    PRIMARY KEY (run_id, chunk_number)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id                INTEGER,
    run_id            TEXT,
    chunk_number      INTEGER,
    stage             TEXT,
    elapsed_s         DOUBLE,
    tokens_in_approx  INTEGER,
    tokens_out_approx INTEGER
);

-- merges removed: computed as (entities_before - entities_after) in queries
CREATE TABLE IF NOT EXISTS resolution_runs (
    id                INTEGER,
    run_id            TEXT,
    strategy          TEXT,
    entities_before   INTEGER,
    entities_after    INTEGER,
    elapsed_s         DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS seq_chunks    START 1;
CREATE SEQUENCE IF NOT EXISTS seq_llm       START 1;
CREATE SEQUENCE IF NOT EXISTS seq_res       START 1;
CREATE SEQUENCE IF NOT EXISTS seq_sub_tax   START 1;

CREATE TABLE IF NOT EXISTS sub_taxonomy_approvals (
    id                INTEGER PRIMARY KEY DEFAULT nextval('seq_sub_tax'),
    proposal_id       TEXT,
    action            TEXT,
    leaf_class_uri    TEXT,
    entity_uri        TEXT,
    class_uris        TEXT,
    merged_classes    INTEGER,
    entity_retyped    BOOLEAN,
    recorded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class NullBenchmarkStore:
    """No-op implementation used when DuckDB is not installed."""

    def start_run(self, **kwargs) -> str:
        return "null-run"

    def finish_run(self, *args, **kwargs):
        pass

    def record_chunk(self, *args, **kwargs):
        pass

    def record_llm_call(self, *args, **kwargs):
        pass

    def record_resolution(self, *args, **kwargs):
        pass

    def record_sub_taxonomy_approval(self, *args, **kwargs):
        pass

    def query(self, sql: str):
        print("DuckDB not installed — benchmark queries unavailable.")
        print("Install with: uv sync --extra benchmark")
        return None

    def clear(self):
        pass

    def close(self):
        pass

    SUMMARY_SQL = ""
    CHUNK_SQL = ""
    LLM_SQL = ""


def create_benchmark_store(db_path: str = _DB_PATH) -> "BenchmarkStore | NullBenchmarkStore":
    """Return a live BenchmarkStore if DuckDB is available, else NullBenchmarkStore."""
    if _DUCKDB_AVAILABLE:
        return BenchmarkStore(db_path)
    import logging
    logging.getLogger(__name__).debug(
        "duckdb not installed — benchmarking disabled. "
        "Install with: uv sync --extra benchmark"
    )
    return NullBenchmarkStore()


class BenchmarkStore:
    """Record and query pipeline benchmark metrics."""

    def __init__(self, db_path: str = _DB_PATH):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(db_path)
        self._con.execute(_DDL)

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(
        self,
        document_filename: str,
        document_id: str,
        word_count: int,
        llm_provider: str,
        llm_model: str,
        resolution_enabled: bool,
        resolution_strategies: list,
        max_chunks: Optional[int] = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        self._con.execute(
            """
            INSERT INTO runs (
                run_id, started_at, document_filename, document_id,
                word_count, max_chunks, llm_provider, llm_model,
                resolution_enabled,
                entities_raw, entities_resolved, triples, proposals
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
            """,
            [
                run_id,
                datetime.now(timezone.utc),
                document_filename,
                document_id,
                word_count,
                max_chunks,
                llm_provider,
                llm_model,
                resolution_enabled,
            ],
        )
        # Strategies in normalized table — one row per strategy, ordered
        for pos, strategy in enumerate(resolution_strategies):
            self._con.execute(
                "INSERT INTO run_strategies (run_id, position, strategy) VALUES (?, ?, ?)",
                [run_id, pos, strategy],
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        chunk_count: int,
        entities_raw: int,
        entities_resolved: int,
        triples: int,
        elapsed_s: float,
        proposals: int,
    ):
        self._con.execute(
            """
            UPDATE runs SET
                finished_at        = ?,
                chunk_count        = ?,
                entities_raw       = ?,
                entities_resolved  = ?,
                triples            = ?,
                elapsed_s          = ?,
                proposals          = ?
            WHERE run_id = ?
            """,
            [
                datetime.now(timezone.utc),
                chunk_count,
                entities_raw,
                entities_resolved,
                triples,
                elapsed_s,
                proposals,
                run_id,
            ],
        )

    # ------------------------------------------------------------------
    # Chunk metrics
    # ------------------------------------------------------------------

    def record_chunk(
        self,
        run_id: str,
        chunk_number: int,
        word_count: int,
        entities: int,
        relationships: int,
        elapsed_s: float,
    ):
        self._con.execute(
            """
            INSERT INTO chunks (id, run_id, chunk_number, word_count,
                                entities, relationships, elapsed_s)
            VALUES (nextval('seq_chunks'), ?, ?, ?, ?, ?, ?)
            """,
            [run_id, chunk_number, word_count, entities, relationships, elapsed_s],
        )

    # ------------------------------------------------------------------
    # LLM call metrics
    # ------------------------------------------------------------------

    def record_llm_call(
        self,
        run_id: str,
        stage: str,
        elapsed_s: float,
        chunk_number: int = 0,
        tokens_in_approx: int = 0,
        tokens_out_approx: int = 0,
    ):
        self._con.execute(
            """
            INSERT INTO llm_calls (id, run_id, chunk_number, stage,
                                   elapsed_s, tokens_in_approx, tokens_out_approx)
            VALUES (nextval('seq_llm'), ?, ?, ?, ?, ?, ?)
            """,
            [run_id, chunk_number, stage, elapsed_s, tokens_in_approx, tokens_out_approx],
        )

    # ------------------------------------------------------------------
    # Resolution metrics
    # ------------------------------------------------------------------

    def record_resolution(
        self,
        run_id: str,
        strategy: str,
        entities_before: int,
        entities_after: int,
        elapsed_s: float,
    ):
        self._con.execute(
            """
            INSERT INTO resolution_runs (id, run_id, strategy,
                                         entities_before, entities_after,
                                         elapsed_s)
            VALUES (nextval('seq_res'), ?, ?, ?, ?, ?)
            """,
            [run_id, strategy, entities_before, entities_after, elapsed_s],
        )

    def record_sub_taxonomy_approval(
        self,
        proposal_id: str,
        action: str,
        leaf_class_uri: str = "",
        entity_uri: Optional[str] = None,
        class_uris: Optional[list] = None,
        merged_classes: int = 0,
        entity_retyped: bool = False,
    ) -> None:
        import json
        self._con.execute(
            """
            INSERT INTO sub_taxonomy_approvals (
                proposal_id, action, leaf_class_uri, entity_uri,
                class_uris, merged_classes, entity_retyped
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                proposal_id,
                action,
                leaf_class_uri or "",
                entity_uri or "",
                json.dumps(class_uris or []),
                merged_classes,
                entity_retyped,
            ],
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def query(self, sql: str) -> duckdb.DuckDBPyRelation:
        return self._con.sql(sql)

    def clear(self):
        for table in (
            "sub_taxonomy_approvals",
            "resolution_runs",
            "llm_calls",
            "chunks",
            "run_strategies",
            "runs",
        ):
            self._con.execute(f"DELETE FROM {table}")

    def close(self):
        self._con.close()

    # ------------------------------------------------------------------
    # Canned summary views
    # ------------------------------------------------------------------

    SUMMARY_SQL = """
        SELECT
            strftime(started_at, '%Y-%m-%d %H:%M')  AS started,
            document_filename                         AS document,
            chunk_count                               AS chunks,
            entities_raw                              AS entities,
            entities_resolved                         AS resolved,
            triples,
            proposals,
            round(elapsed_s, 1)                       AS elapsed_s,
            llm_model                                 AS model,
            CASE WHEN resolution_enabled
                 THEN (SELECT string_agg(strategy, '→' ORDER BY position)
                       FROM run_strategies rs WHERE rs.run_id = r.run_id)
                 ELSE 'off'
            END                                       AS resolution
        FROM runs r
        ORDER BY started_at DESC
        LIMIT 20
    """

    CHUNK_SQL = """
        SELECT
            r.document_filename AS document,
            c.chunk_number      AS chunk,
            c.word_count        AS words,
            c.entities,
            c.relationships     AS rels,
            round(c.elapsed_s, 1) AS elapsed_s
        FROM chunks c
        JOIN runs r USING (run_id)
        ORDER BY r.started_at DESC, c.chunk_number
        LIMIT 50
    """

    LLM_SQL = """
        SELECT
            r.document_filename AS document,
            l.stage,
            l.chunk_number      AS chunk,
            round(l.elapsed_s, 1) AS elapsed_s
        FROM llm_calls l
        JOIN runs r USING (run_id)
        ORDER BY r.started_at DESC, l.chunk_number, l.stage
        LIMIT 100
    """
