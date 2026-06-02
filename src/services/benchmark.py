"""Benchmark metrics display and management."""
import re
from typing import Any, Dict, List, Optional

from src.storage.benchmark_store import BenchmarkStore, create_benchmark_store
from src.services.models import TableResult


_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|COPY|PRAGMA|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def validate_readonly_sql(sql: str) -> str:
    stripped = sql.strip()
    if not stripped:
        raise ValueError("sql is required")
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("only SELECT queries are allowed")
    if ";" in stripped.rstrip(";"):
        raise ValueError("multi-statement queries are not allowed")
    if _FORBIDDEN_SQL.search(stripped):
        raise ValueError("query contains disallowed keywords")
    return stripped


def _relation_to_table(rel) -> TableResult:
    if rel is None:
        return TableResult(columns=[], rows=[], text="")
    try:
        df = rel.fetchdf()
        columns = [str(c) for c in df.columns]
        rows = df.values.tolist()
        return TableResult(columns=columns, rows=rows, text=str(rel))
    except Exception:
        return TableResult(columns=[], rows=[], text=str(rel))


class BenchmarkService:
    def get_view(self, view: str = "runs") -> TableResult:
        if view == "runs":
            sql = BenchmarkStore.SUMMARY_SQL
        elif view == "chunks":
            sql = BenchmarkStore.CHUNK_SQL
        elif view == "llm":
            sql = BenchmarkStore.LLM_SQL
        else:
            return TableResult(columns=[], rows=[], text=f"Unknown view: {view}")
        return self.query(sql)

    def query(self, sql: str) -> TableResult:
        safe_sql = validate_readonly_sql(sql)
        bench = create_benchmark_store()
        try:
            rel = bench.query(safe_sql)
            return _relation_to_table(rel)
        finally:
            bench.close()

    def show(self, view: str = "runs", sql: Optional[str] = None) -> TableResult:
        if sql:
            return self.query(sql)
        return self.get_view(view)

    def clear(self) -> None:
        bench = create_benchmark_store()
        bench.clear()
        bench.close()

    def as_json(self, table: TableResult) -> Dict[str, Any]:
        return {"columns": table.columns, "rows": table.rows}
