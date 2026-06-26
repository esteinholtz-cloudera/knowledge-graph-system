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

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

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
    proposals         INTEGER,
    run_snapshot_json TEXT
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

CREATE SEQUENCE IF NOT EXISTS seq_ee_judge START 1;

CREATE TABLE IF NOT EXISTS ee_judge_evaluations (
    id                INTEGER PRIMARY KEY DEFAULT nextval('seq_ee_judge'),
    eval_id           TEXT UNIQUE,
    run_id            TEXT,
    recorded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    document_filename TEXT,
    document_id       TEXT,
    markup_path       TEXT,
    source_path       TEXT,
    llm_model         TEXT,
    domain            TEXT,
    grade             TEXT,
    grade_score       DOUBLE,
    summary           TEXT,
    unique_entities   INTEGER,
    marked_spans      INTEGER,
    orphan_entities   INTEGER,
    orphan_rate       DOUBLE,
    verbatim_issues   INTEGER,
    metrics_json      TEXT,
    prompts_before    TEXT,
    prompts_after     TEXT,
    optimization_applied BOOLEAN DEFAULT FALSE
);
"""


def _migrate_runs_schema(con: "duckdb.DuckDBPyConnection") -> None:
    """Add columns introduced after initial schema without recreating tables."""
    existing = {row[0] for row in con.execute("DESCRIBE runs").fetchall()}
    if "run_snapshot_json" not in existing:
        con.execute("ALTER TABLE runs ADD COLUMN run_snapshot_json TEXT")
    if "tokens_in_total" not in existing:
        con.execute("ALTER TABLE runs ADD COLUMN tokens_in_total INTEGER")
    if "tokens_out_total" not in existing:
        con.execute("ALTER TABLE runs ADD COLUMN tokens_out_total INTEGER")


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

    def record_ee_judge_evaluation(self, **kwargs) -> str:
        return "null-eval"

    def update_ee_judge_prompts_after(self, *args, **kwargs):
        pass

    def get_run_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        return None

    def restore_run_snapshot(self, run_id: str, project_root: Path) -> Path:
        raise RuntimeError("Benchmark store unavailable — install duckdb extra")

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
        _migrate_runs_schema(self._con)

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
        run_snapshot_json: Optional[str] = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        self._con.execute(
            """
            INSERT INTO runs (
                run_id, started_at, document_filename, document_id,
                word_count, max_chunks, llm_provider, llm_model,
                resolution_enabled, run_snapshot_json,
                entities_raw, entities_resolved, triples, proposals
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
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
                run_snapshot_json,
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
        token_row = self._con.execute(
            """
            SELECT
                coalesce(sum(tokens_in_approx), 0),
                coalesce(sum(tokens_out_approx), 0)
            FROM llm_calls
            WHERE run_id = ?
            """,
            [run_id],
        ).fetchone()
        tokens_in_total = int(token_row[0]) if token_row else 0
        tokens_out_total = int(token_row[1]) if token_row else 0
        self._con.execute(
            """
            UPDATE runs SET
                finished_at        = ?,
                chunk_count        = ?,
                entities_raw       = ?,
                entities_resolved  = ?,
                triples            = ?,
                elapsed_s          = ?,
                proposals          = ?,
                tokens_in_total    = ?,
                tokens_out_total   = ?
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
                tokens_in_total,
                tokens_out_total,
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

    def record_ee_judge_evaluation(
        self,
        *,
        document_filename: str,
        markup_path: str,
        source_path: str,
        llm_model: str,
        domain: str,
        grade: str,
        summary: str,
        unique_entities: int,
        marked_spans: int,
        orphan_entities: int,
        orphan_rate: float,
        verbatim_issues: int,
        metrics_json: str,
        prompts_before: str,
        run_id: Optional[str] = None,
        document_id: str = "",
        grade_score: Optional[float] = None,
        prompts_after: Optional[str] = None,
        optimization_applied: bool = False,
    ) -> str:
        """Record an LLM-as-judge entity extraction evaluation."""
        eval_id = str(uuid.uuid4())
        self._con.execute(
            """
            INSERT INTO ee_judge_evaluations (
                eval_id, run_id, document_filename, document_id,
                markup_path, source_path, llm_model, domain,
                grade, grade_score, summary,
                unique_entities, marked_spans, orphan_entities,
                orphan_rate, verbatim_issues,
                metrics_json, prompts_before, prompts_after,
                optimization_applied
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                eval_id,
                run_id,
                document_filename,
                document_id,
                markup_path,
                source_path,
                llm_model,
                domain,
                grade,
                grade_score,
                summary,
                unique_entities,
                marked_spans,
                orphan_entities,
                orphan_rate,
                verbatim_issues,
                metrics_json,
                prompts_before,
                prompts_after,
                optimization_applied,
            ],
        )
        return eval_id

    def update_ee_judge_prompts_after(
        self,
        eval_id: str,
        prompts_after: str,
    ) -> None:
        """Attach post-optimization prompts to an existing evaluation row."""
        self._con.execute(
            """
            UPDATE ee_judge_evaluations SET
                prompts_after = ?,
                optimization_applied = TRUE
            WHERE eval_id = ?
            """,
            [prompts_after, eval_id],
        )

    def get_run_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return stored prompt/chunk snapshot for a run, or None if missing."""
        row = self._con.execute(
            "SELECT run_snapshot_json FROM runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if not row or not row[0]:
            return None
        return json.loads(row[0])

    def restore_run_snapshot(self, run_id: str, project_root: Path) -> Path:
        """Write stored prompt files back to disk for reproducibility."""
        from src.extraction.prompt_store import PromptStore

        snapshot = self.get_run_snapshot(run_id)
        if snapshot is None:
            raise ValueError(f"No prompt snapshot stored for run {run_id}")
        return PromptStore(project_root).write_snapshot_files(snapshot)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def query(self, sql: str) -> duckdb.DuckDBPyRelation:
        return self._con.sql(sql)

    def clear(self):
        for table in (
            "ee_judge_evaluations",
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
            tokens_in_total                           AS tokens_in,
            tokens_out_total                          AS tokens_out,
            (run_snapshot_json IS NOT NULL)           AS snapshot,
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
            round(l.elapsed_s, 1) AS elapsed_s,
            l.tokens_in_approx  AS tokens_in,
            l.tokens_out_approx AS tokens_out
        FROM llm_calls l
        JOIN runs r USING (run_id)
        ORDER BY r.started_at DESC, l.chunk_number, l.stage
        LIMIT 100
    """

    EE_JUDGE_SQL = """
        SELECT
            strftime(recorded_at, '%Y-%m-%d %H:%M') AS evaluated,
            document_filename                         AS document,
            llm_model                                 AS model,
            domain,
            grade,
            round(grade_score, 0)                     AS score,
            unique_entities                           AS entities,
            round(orphan_rate * 100, 0)               AS orphan_pct,
            verbatim_issues                           AS verbatim,
            optimization_applied                      AS optimized,
            left(summary, 60)                         AS summary
        FROM ee_judge_evaluations
        ORDER BY recorded_at DESC
        LIMIT 20
    """
