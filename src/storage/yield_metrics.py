"""Per-chunk yield and prompt/chunk budget metrics from benchmark runs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import mean

PROMPT_FILES = (
    "entity.system.txt",
    "entity.user.prefix.txt",
    "entity.user.suffix.txt",
)


def prompt_words(prompts_dir: Path) -> int:
    total = 0
    for name in PROMPT_FILES:
        path = prompts_dir / name
        if path.is_file():
            total += len(path.read_text(encoding="utf-8").split())
    return total


@dataclass(frozen=True)
class ChunkYieldStats:
    run_id: str
    chunk_count: int
    entities_raw: int
    entities_resolved: int
    empty_chunk_rate: float
    mean_entities_per_chunk: float
    min_entities_per_chunk: int
    max_entities_per_chunk: int

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "chunk_count": self.chunk_count,
            "entities_raw": self.entities_raw,
            "entities_resolved": self.entities_resolved,
            "empty_chunk_rate": self.empty_chunk_rate,
            "mean_entities_per_chunk": self.mean_entities_per_chunk,
            "min_entities_per_chunk": self.min_entities_per_chunk,
            "max_entities_per_chunk": self.max_entities_per_chunk,
        }


def chunk_yield_stats(run_id: str, bench) -> ChunkYieldStats:
    rows = bench._con.execute(
        "SELECT entities FROM chunks WHERE run_id = ? ORDER BY chunk_number",
        [run_id],
    ).fetchall()
    run_row = bench._con.execute(
        "SELECT entities_raw, entities_resolved FROM runs WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if not run_row:
        raise RuntimeError(f"No run row for run_id={run_id}")

    counts = [int(row[0]) for row in rows]
    if not counts:
        return ChunkYieldStats(
            run_id=run_id,
            chunk_count=0,
            entities_raw=int(run_row[0]),
            entities_resolved=int(run_row[1]),
            empty_chunk_rate=0.0,
            mean_entities_per_chunk=0.0,
            min_entities_per_chunk=0,
            max_entities_per_chunk=0,
        )

    empty_rate = sum(1 for count in counts if count == 0) / len(counts)
    return ChunkYieldStats(
        run_id=run_id,
        chunk_count=len(counts),
        entities_raw=int(run_row[0]),
        entities_resolved=int(run_row[1]),
        empty_chunk_rate=round(empty_rate, 4),
        mean_entities_per_chunk=round(mean(counts), 2),
        min_entities_per_chunk=min(counts),
        max_entities_per_chunk=max(counts),
    )


def latest_run_id(bench, document_filename: str, llm_model: str) -> str:
    row = bench._con.execute(
        """
        SELECT run_id
        FROM runs
        WHERE document_filename = ? AND llm_model = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        [document_filename, llm_model],
    ).fetchone()
    if not row:
        raise RuntimeError(
            f"No benchmark run for document={document_filename} model={llm_model}"
        )
    return row[0]


def budget_report(
    *,
    prompt_words: int,
    chunk_size: int,
    chunk_strategy: str,
    yield_stats: ChunkYieldStats,
) -> dict:
    total_budget = prompt_words + chunk_size
    return {
        "prompt_words": prompt_words,
        "chunk_size": chunk_size,
        "chunk_strategy": chunk_strategy,
        "total_budget": total_budget,
        **yield_stats.to_dict(),
    }


def yield_regression(
    current: ChunkYieldStats,
    previous: ChunkYieldStats | None,
    *,
    empty_rate_spike: float = 0.10,
    entity_drop_fraction: float = 0.15,
) -> dict:
    """Detect yield collapse vs prior iteration (prompt growth regression)."""
    if previous is None:
        return {
            "regressed": False,
            "reasons": [],
            "empty_chunk_rate_delta": 0.0,
            "entities_raw_retention": 1.0,
        }

    empty_delta = current.empty_chunk_rate - previous.empty_chunk_rate
    retention = (
        current.entities_raw / previous.entities_raw
        if previous.entities_raw > 0
        else 1.0
    )
    reasons: list[str] = []
    if current.empty_chunk_rate >= empty_rate_spike:
        reasons.append(f"empty_chunk_rate={current.empty_chunk_rate:.1%}")
    if empty_delta >= empty_rate_spike and previous.empty_chunk_rate < empty_rate_spike:
        reasons.append(f"empty_chunk_rate_spike (+{empty_delta:.1%})")
    if retention < (1.0 - entity_drop_fraction):
        reasons.append(
            f"entities_raw dropped {100 * (1 - retention):.0f}% "
            f"({previous.entities_raw} → {current.entities_raw})"
        )

    return {
        "regressed": bool(reasons),
        "reasons": reasons,
        "empty_chunk_rate_delta": round(empty_delta, 4),
        "entities_raw_retention": round(retention, 4),
    }
