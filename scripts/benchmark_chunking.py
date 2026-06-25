#!/usr/bin/env python3
"""Compare chunking strategies on a document (structural metrics; optional extraction)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.document.chunking import (
    ChunkStrategy,
    chunk_text,
    chunk_word_start_indices,
    text_to_units,
    word_count,
)

ANALYZE = PROJECT_ROOT / ".cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py"
CONVERGE = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/scripts/check_convergence.py"
THRESHOLDS = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/thresholds-technical.json"
RESULTS = PROJECT_ROOT / "data/chunking_benchmark.json"

PRESETS: list[tuple[str, ChunkStrategy, int, int]] = [
    ("fixed_300_100", "fixed", 300, 100),
    ("recursive_300_50", "recursive", 300, 50),
    ("recursive_350_60", "recursive", 350, 60),
]


@dataclass
class ChunkingReport:
    name: str
    strategy: str
    chunk_size: int
    overlap: int
    chunk_count: int
    avg_words: float
    min_words: int
    max_words: int
    mid_sentence_boundaries: int
    boundary_count: int


def word_unit_ids(text: str) -> list[int]:
    ids: list[int] = []
    for unit_index, unit in enumerate(text_to_units(text, max_words=10_000)):
        ids.extend([unit_index] * word_count(unit))
    return ids


def mid_sentence_boundary_count(text: str, strategy: ChunkStrategy, chunk_size: int, overlap: int) -> tuple[int, int]:
    unit_ids = word_unit_ids(text)
    starts = chunk_word_start_indices(
        text, strategy=strategy, chunk_size=chunk_size, overlap=overlap,
    )
    if len(starts) <= 1:
        return 0, 0
    mid_sentence = sum(
        1 for start in starts[1:]
        if 0 < start < len(unit_ids) and unit_ids[start - 1] == unit_ids[start]
    )
    return mid_sentence, len(starts) - 1


def analyze_structure(name: str, strategy: ChunkStrategy, chunk_size: int, overlap: int, text: str) -> ChunkingReport:
    chunks = chunk_text(text, strategy=strategy, chunk_size=chunk_size, overlap=overlap)
    sizes = [word_count(chunk) for chunk in chunks] or [0]
    mid_sentence, boundary_count = mid_sentence_boundary_count(text, strategy, chunk_size, overlap)
    return ChunkingReport(
        name=name,
        strategy=strategy,
        chunk_size=chunk_size,
        overlap=overlap,
        chunk_count=len(chunks),
        avg_words=round(mean(sizes), 1),
        min_words=min(sizes),
        max_words=max(sizes),
        mid_sentence_boundaries=mid_sentence,
        boundary_count=boundary_count,
    )


def run_extraction(source: Path, domain: str, max_chunks: int | None) -> None:
    cmd = ["uv", "run", "python", "main.py", "process", str(source), "--domain", domain]
    if max_chunks is not None:
        cmd.extend(["--max-chunks", str(max_chunks)])
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def measure_markup(source: Path) -> dict:
    stem = source.stem
    markup = PROJECT_ROOT / "data/documents" / f"{stem}_markup.html"
    metrics_file = PROJECT_ROOT / "data/chunking_metrics.tmp.json"
    with metrics_file.open("w", encoding="utf-8") as handle:
        subprocess.run(
            ["uv", "run", "python", str(ANALYZE), str(markup), str(source), "--json"],
            cwd=PROJECT_ROOT,
            check=True,
            stdout=handle,
        )
    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    result = subprocess.run(
        [
            "uv", "run", "python", str(CONVERGE),
            "--metrics-file", str(metrics_file),
            "--markup", str(markup),
            "--thresholds-file", str(THRESHOLDS),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    convergence = json.loads(result.stdout)
    return {
        "unique_entities": metrics["unique_entities"],
        "orphan_rate": convergence["rates"]["orphan_rate"],
        "verbatim_rate": convergence["rates"]["verbatim_rate"],
        "error_score": convergence["rates"]["error_score"],
    }


def print_table(rows: list[dict]) -> None:
    headers = ["name", "chunks", "avg_w", "mid_sent", "entities", "orphan", "verbatim", "error"]
    print(" ".join(f"{header:>10}" for header in headers))
    print("-" * 90)
    for row in rows:
        print(
            f"{row.get('name', ''):>10} "
            f"{row.get('chunk_count', ''):>10} "
            f"{row.get('avg_words', ''):>10} "
            f"{row.get('mid_sentence_boundaries', ''):>10} "
            f"{row.get('unique_entities', '-'):>10} "
            f"{row.get('orphan_rate', '-'):>10} "
            f"{row.get('verbatim_rate', '-'):>10} "
            f"{row.get('error_score', '-'):>10}"
        )


def apply_chunk_settings(strategy: ChunkStrategy, chunk_size: int, overlap: int) -> None:
    import yaml

    config_path = PROJECT_ROOT / "config/config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    llm = config.setdefault("llm", {})
    llm["chunk_strategy"] = strategy
    llm["chunk_size"] = chunk_size
    llm["overlap"] = overlap
    for model_cfg in llm.get("model_settings", {}).values():
        model_cfg["chunk_strategy"] = strategy
        model_cfg["chunk_size"] = chunk_size
        model_cfg["overlap"] = overlap
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "input/ZDU_prereqs.txt")
    parser.add_argument("--domain", default="technical")
    parser.add_argument("--extract", action="store_true", help="Run full extraction per strategy (slow)")
    parser.add_argument("--max-chunks", type=int, default=None)
    args = parser.parse_args()

    config_path = PROJECT_ROOT / "config/config.yaml"
    original_config = config_path.read_text(encoding="utf-8")
    text = args.source.read_text(encoding="utf-8")
    rows: list[dict] = []

    try:
        for name, strategy, chunk_size, overlap in PRESETS:
            report = analyze_structure(name, strategy, chunk_size, overlap, text)
            row = asdict(report)
            if args.extract:
                apply_chunk_settings(strategy, chunk_size, overlap)
                run_extraction(args.source, args.domain, args.max_chunks)
                row.update(measure_markup(args.source))
            rows.append(row)
    finally:
        config_path.write_text(original_config, encoding="utf-8")

    print_table(rows)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved to {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
