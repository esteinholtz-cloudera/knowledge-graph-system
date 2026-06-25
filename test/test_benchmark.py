"""
Tests for the benchmark storage plugin.

These tests use an in-memory DuckDB database (no file I/O) and do NOT
require the LLM to be running — they test the storage layer in isolation.

Skipped automatically when the `benchmark` extra (duckdb) is not installed.

Run with:
    uv run pytest test/test_benchmark.py -v
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.benchmark_store import _DUCKDB_AVAILABLE, NullBenchmarkStore

pytestmark = pytest.mark.skipif(
    not _DUCKDB_AVAILABLE,
    reason="duckdb not installed — run `uv sync --extra benchmark` to enable",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    """In-memory BenchmarkStore (no file written)."""
    from src.storage.benchmark_store import BenchmarkStore
    s = BenchmarkStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def populated_store(store):
    """Store with one complete run recorded."""
    run_id = store.start_run(
        document_filename="skills.txt",
        document_id="abc123",
        word_count=570,
        llm_provider="lmstudio",
        llm_model="qwen3-14b",
        resolution_enabled=True,
        resolution_strategies=["rule_based", "embedding"],
        max_chunks=None,
    )
    store.record_chunk(run_id, 1, 570, 12, 8, 34.5)
    store.record_llm_call(run_id, "entity_extraction", 18.2, chunk_number=1)
    store.record_llm_call(run_id, "relationship_extraction", 16.3, chunk_number=1)
    store.record_resolution(run_id, "rule_based+embedding", 12, 10, 2.1)
    store.finish_run(run_id, 1, 12, 10, 8, 55.1, 0)
    return store, run_id


# ---------------------------------------------------------------------------
# Schema / write tests
# ---------------------------------------------------------------------------

class TestBenchmarkWrite:
    """Verify data is written correctly to each table."""

    def test_run_created(self, populated_store):
        store, run_id = populated_store
        rows = store.query("SELECT * FROM runs").fetchall()
        assert len(rows) == 1

    def test_strategies_normalised(self, populated_store):
        store, run_id = populated_store
        rows = store.query(
            "SELECT position, strategy FROM run_strategies ORDER BY position"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0] == (0, "rule_based")
        assert rows[1] == (1, "embedding")

    def test_chunk_recorded(self, populated_store):
        store, run_id = populated_store
        rows = store.query("SELECT * FROM chunks").fetchall()
        assert len(rows) == 1
        cols = {d[0]: v for d, v in zip(store._con.description or [], rows[0])}
        # column by index: id, run_id, chunk_number, word_count, entities, relationships, elapsed_s
        row = store.query(
            "SELECT chunk_number, word_count, entities, relationships FROM chunks"
        ).fetchone()
        assert row == (1, 570, 12, 8)

    def test_llm_calls_recorded(self, populated_store):
        store, _ = populated_store
        rows = store.query(
            "SELECT stage FROM llm_calls ORDER BY stage"
        ).fetchall()
        stages = [r[0] for r in rows]
        assert "entity_extraction" in stages
        assert "relationship_extraction" in stages

    def test_resolution_recorded(self, populated_store):
        store, _ = populated_store
        row = store.query(
            "SELECT entities_before, entities_after FROM resolution_runs"
        ).fetchone()
        assert row == (12, 10)

    def test_merges_not_stored(self, populated_store):
        """merges is a derived value — verify it is NOT a column."""
        store, _ = populated_store
        columns = [
            col[0]
            for col in store.query("DESCRIBE resolution_runs").fetchall()
        ]
        assert "merges" not in columns

    def test_merges_computable(self, populated_store):
        store, _ = populated_store
        row = store.query(
            "SELECT entities_before - entities_after AS merges FROM resolution_runs"
        ).fetchone()
        assert row[0] == 2  # 12 - 10


# ---------------------------------------------------------------------------
# Query / view tests
# ---------------------------------------------------------------------------

class TestBenchmarkQuery:
    """Verify canned summary queries return expected structure."""

    def test_summary_view_runs(self, populated_store):
        store, _ = populated_store
        from src.storage.benchmark_store import BenchmarkStore
        result = store.query(BenchmarkStore.SUMMARY_SQL)
        rows = result.fetchall()
        assert len(rows) == 1
        # Column names
        col_names = [d[0] for d in result.description]
        assert "document" in col_names
        assert "entities" in col_names
        assert "resolution" in col_names

    def test_summary_strategy_column(self, populated_store):
        """Resolution strategies must appear joined in order."""
        store, _ = populated_store
        from src.storage.benchmark_store import BenchmarkStore
        result = store.query(BenchmarkStore.SUMMARY_SQL)
        row = result.fetchone()
        col_names = [d[0] for d in result.description]
        resolution_idx = col_names.index("resolution")
        assert row[resolution_idx] == "rule_based→embedding"

    def test_chunk_view(self, populated_store):
        store, _ = populated_store
        from src.storage.benchmark_store import BenchmarkStore
        rows = store.query(BenchmarkStore.CHUNK_SQL).fetchall()
        assert len(rows) == 1

    def test_llm_view(self, populated_store):
        store, _ = populated_store
        from src.storage.benchmark_store import BenchmarkStore
        rows = store.query(BenchmarkStore.LLM_SQL).fetchall()
        assert len(rows) == 2

    def test_custom_sql(self, populated_store):
        store, _ = populated_store
        row = store.query(
            "SELECT llm_model FROM runs"
        ).fetchone()
        assert row[0] == "qwen3-14b"

    def test_clear_removes_all(self, populated_store):
        store, _ = populated_store
        store.clear()
        for table in (
            "runs",
            "run_strategies",
            "chunks",
            "llm_calls",
            "resolution_runs",
            "ee_judge_evaluations",
        ):
            count = store.query(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"Table {table} not empty after clear()"


class TestEeJudgeEvaluation:
    def test_record_and_update_prompts(self, store):
        import json

        eval_id = store.record_ee_judge_evaluation(
            document_filename="ZDU_prereqs.txt",
            document_id="ZDU_prereqs",
            markup_path="data/documents/ZDU_prereqs_markup.html",
            source_path="input/ZDU_prereqs.txt",
            llm_model="qwen3-30b",
            domain="technical",
            grade="B-",
            grade_score=80.0,
            summary="usable but noisy",
            unique_entities=121,
            marked_spans=311,
            orphan_entities=35,
            orphan_rate=0.29,
            verbatim_issues=17,
            metrics_json=json.dumps({"unique_entities": 121}),
            prompts_before=json.dumps({"files": {"entity.system.txt": "before"}}),
        )
        row = store.query(
            "SELECT grade, optimization_applied, prompts_after FROM ee_judge_evaluations"
        ).fetchone()
        assert row[0] == "B-"
        assert row[1] is False
        assert row[2] is None

        store.update_ee_judge_prompts_after(
            eval_id,
            json.dumps({"files": {"entity.system.txt": "after"}}),
        )
        row = store.query(
            "SELECT optimization_applied, prompts_after FROM ee_judge_evaluations"
        ).fetchone()
        assert row[0] is True
        assert "after" in row[1]

    def test_ee_judge_view(self, store):
        import json

        store.record_ee_judge_evaluation(
            document_filename="doc.txt",
            document_id="doc",
            markup_path="m.html",
            source_path="doc.txt",
            llm_model="test-model",
            domain="default",
            grade="A",
            grade_score=93.0,
            summary="good",
            unique_entities=10,
            marked_spans=20,
            orphan_entities=1,
            orphan_rate=0.1,
            verbatim_issues=0,
            metrics_json="{}",
            prompts_before="{}",
        )
        from src.storage.benchmark_store import BenchmarkStore

        rows = store.query(BenchmarkStore.EE_JUDGE_SQL).fetchall()
        assert len(rows) == 1


class TestRunSnapshot:
    def test_snapshot_stored_and_restored(self, store, tmp_path):
        import json

        snapshot = {
            "prompts_dir": "prompts/test-model/technical",
            "domain": "technical",
            "llm_model": "test-model",
            "chunk_size": 100,
            "overlap": 25,
            "section_size": 5,
            "files": {
                "entity.system.txt": "ENTITY SYSTEM",
                "entity.user.prefix.txt": "PREFIX",
                "entity.user.suffix.txt": "SUFFIX",
                "relationship.system.txt": "REL SYSTEM",
                "relationship.user.prefix.txt": "REL PREFIX",
                "relationship.user.suffix.txt": "REL SUFFIX",
            },
        }
        run_id = store.start_run(
            document_filename="doc.txt",
            document_id="doc",
            word_count=100,
            llm_provider="lmstudio",
            llm_model="test-model",
            resolution_enabled=False,
            resolution_strategies=[],
            run_snapshot_json=json.dumps(snapshot),
        )
        loaded = store.get_run_snapshot(run_id)
        assert loaded == snapshot

        prompts_dir = store.restore_run_snapshot(run_id, tmp_path)
        assert prompts_dir == tmp_path / "prompts/test-model/technical"
        assert (prompts_dir / "entity.system.txt").read_text(encoding="utf-8") == "ENTITY SYSTEM"

    def test_restore_missing_snapshot_raises(self, store, tmp_path):
        run_id = store.start_run(
            document_filename="doc.txt",
            document_id="doc",
            word_count=100,
            llm_provider="lmstudio",
            llm_model="test-model",
            resolution_enabled=False,
            resolution_strategies=[],
        )
        with pytest.raises(ValueError, match="No prompt snapshot"):
            store.restore_run_snapshot(run_id, tmp_path)


# ---------------------------------------------------------------------------
# NullBenchmarkStore tests (no duckdb required — always runs)
# ---------------------------------------------------------------------------

class TestNullBenchmarkStore:
    """NullBenchmarkStore should silently no-op all calls."""

    # Override skipif for this class only
    pytestmark = []

    def test_start_run_returns_string(self):
        s = NullBenchmarkStore()
        run_id = s.start_run(
            document_filename="x.txt", document_id="y", word_count=1,
            llm_provider="ollama", llm_model="llama3.2",
            resolution_enabled=False, resolution_strategies=[],
        )
        assert isinstance(run_id, str)

    def test_all_record_methods_are_noop(self):
        s = NullBenchmarkStore()
        run_id = s.start_run(
            document_filename="x.txt", document_id="y", word_count=1,
            llm_provider="ollama", llm_model="llama3.2",
            resolution_enabled=False, resolution_strategies=[],
        )
        s.record_chunk(run_id, 1, 100, 5, 3, 1.0)
        s.record_llm_call(run_id, "entity_extraction", 1.0)
        s.record_resolution(run_id, "rule_based", 5, 4, 0.1)
        s.record_ee_judge_evaluation(
            document_filename="x.txt",
            markup_path="m.html",
            source_path="x.txt",
            llm_model="llama3.2",
            domain="default",
            grade="B",
            summary="ok",
            unique_entities=1,
            marked_spans=1,
            orphan_entities=0,
            orphan_rate=0.0,
            verbatim_issues=0,
            metrics_json="{}",
            prompts_before="{}",
        )
        s.update_ee_judge_prompts_after("null-eval", "{}")
        s.finish_run(run_id, 1, 5, 4, 3, 2.0, 0)
        s.clear()
        s.close()  # no exception expected
