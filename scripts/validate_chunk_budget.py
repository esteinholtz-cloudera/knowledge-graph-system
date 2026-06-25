#!/usr/bin/env python3
"""Controlled chunk-size sweep at fixed prompt content (budget validation)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.document.chunking import chunk_text, word_count
from src.storage.benchmark_store import create_benchmark_store
from src.storage.yield_metrics import chunk_yield_stats, latest_run_id, prompt_words as count_prompt_words

ANALYZE = PROJECT_ROOT / ".cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py"
CONVERGE = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/scripts/check_convergence.py"
THRESHOLDS = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/thresholds-technical.json"
CONFIG_PATH = PROJECT_ROOT / "config/config.yaml"
RESULTS_PATH = PROJECT_ROOT / "data/chunk_budget_validation.json"

PROMPT_FILES = (
    "entity.system.txt",
    "entity.user.prefix.txt",
    "entity.user.suffix.txt",
)
DEFAULT_MODEL = "qwen3-30b-a3b-instruct-2507-mlx"
DEFAULT_PROMPTS = PROJECT_ROOT / "prompts" / DEFAULT_MODEL / "technical"


def overlap_for(chunk_size: int) -> int:
    return max(chunk_size // 5, 20)


@dataclass
class BudgetRunReport:
    chunk_size: int
    overlap: int
    chunk_count: int
    prompt_words: int
    total_budget: int
    entities_raw: int
    entities_resolved: int
    empty_chunk_rate: float
    mean_entities_per_chunk: float
    min_entities_per_chunk: int
    max_entities_per_chunk: int
    orphan_rate: float
    verbatim_rate: float
    error_score: float
    run_id: str


def load_yaml() -> tuple[dict, str]:
    import yaml

    text = CONFIG_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(text), text


def save_yaml(config: dict) -> None:
    import yaml

    CONFIG_PATH.write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def apply_chunk_settings(chunk_size: int, overlap: int, model: str) -> None:
    config, _ = load_yaml()
    llm = config.setdefault("llm", {})
    llm["chunk_strategy"] = "recursive"
    llm["chunk_size"] = chunk_size
    llm["overlap"] = overlap
    model_settings = llm.setdefault("model_settings", {})
    model_cfg = model_settings.setdefault(model, {})
    model_cfg["chunk_strategy"] = "recursive"
    model_cfg["chunk_size"] = chunk_size
    model_cfg["overlap"] = overlap
    save_yaml(config)


def run_extraction(source: Path, domain: str) -> None:
    subprocess.run(
        ["uv", "run", "python", "main.py", "process", str(source), "--domain", domain],
        cwd=PROJECT_ROOT,
        check=True,
    )


def measure_markup(source: Path) -> dict:
    stem = source.stem
    markup = PROJECT_ROOT / "data/documents" / f"{stem}_markup.html"
    metrics_file = PROJECT_ROOT / "data/chunk_budget_metrics.tmp.json"
    with metrics_file.open("w", encoding="utf-8") as handle:
        subprocess.run(
            ["uv", "run", "python", str(ANALYZE), str(markup), str(source), "--json"],
            cwd=PROJECT_ROOT,
            check=True,
            stdout=handle,
        )
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
    return convergence["rates"]


def validate_one(
    source: Path,
    domain: str,
    chunk_size: int,
    prompt_w: int,
    model: str,
) -> BudgetRunReport:
    overlap = overlap_for(chunk_size)
    apply_chunk_settings(chunk_size, overlap, model)
    text = source.read_text(encoding="utf-8")
    chunk_count = len(
        chunk_text(text, strategy="recursive", chunk_size=chunk_size, overlap=overlap)
    )
    run_extraction(source, domain)
    bench = create_benchmark_store()
    run_id = latest_run_id(bench, source.name, model)
    yield_stats = chunk_yield_stats(run_id, bench)
    bench.close()
    rates = measure_markup(source)

    return BudgetRunReport(
        chunk_size=chunk_size,
        overlap=overlap,
        chunk_count=chunk_count,
        prompt_words=prompt_w,
        total_budget=prompt_w + chunk_size,
        entities_raw=yield_stats.entities_raw,
        entities_resolved=yield_stats.entities_resolved,
        empty_chunk_rate=yield_stats.empty_chunk_rate,
        mean_entities_per_chunk=yield_stats.mean_entities_per_chunk,
        min_entities_per_chunk=yield_stats.min_entities_per_chunk,
        max_entities_per_chunk=yield_stats.max_entities_per_chunk,
        orphan_rate=rates["orphan_rate"],
        verbatim_rate=rates["verbatim_rate"],
        error_score=rates["error_score"],
        run_id=run_id,
    )


def _strictly_increasing(values: list[float], *, epsilon: float = 0.005) -> bool:
    if len(values) < 2:
        return False
    return all(
        values[index + 1] >= values[index] + epsilon
        for index in range(len(values) - 1)
    )


def _strictly_decreasing_ints(values: list[int]) -> bool:
    if len(values) < 2:
        return False
    return all(values[index] > values[index + 1] for index in range(len(values) - 1))


def analyze_monotonicity(rows: list[BudgetRunReport]) -> dict:
    by_chunk = sorted(rows, key=lambda row: row.chunk_size)
    metrics = {
        "empty_chunk_rate": [row.empty_chunk_rate for row in by_chunk],
        "error_score": [row.error_score for row in by_chunk],
        "orphan_rate": [row.orphan_rate for row in by_chunk],
        "verbatim_rate": [row.verbatim_rate for row in by_chunk],
        "entities_raw": [row.entities_raw for row in by_chunk],
        "mean_entities_per_chunk": [row.mean_entities_per_chunk for row in by_chunk],
    }
    error_increases = _strictly_increasing(metrics["error_score"])
    empty_increases = (
        max(metrics["empty_chunk_rate"]) >= 0.05
        and _strictly_increasing(metrics["empty_chunk_rate"], epsilon=0.01)
    )
    yield_decreases = _strictly_decreasing_ints(metrics["entities_raw"])
    largest_vs_smallest_error = (
        metrics["error_score"][-1] - metrics["error_score"][0]
        if metrics["error_score"]
        else 0.0
    )
    largest_vs_smallest_yield = (
        metrics["entities_raw"][0] - metrics["entities_raw"][-1]
        if metrics["entities_raw"]
        else 0
    )

    if error_increases and yield_decreases:
        verdict = "strong"
    elif error_increases or empty_increases or (
        yield_decreases and largest_vs_smallest_yield >= 5
    ):
        verdict = "weak"
    else:
        verdict = "none"

    return {
        "chunk_sizes": [row.chunk_size for row in by_chunk],
        "metrics": metrics,
        "error_score_increases_with_chunk": error_increases,
        "empty_chunk_rate_increases_with_chunk": empty_increases,
        "entities_raw_decreases_with_chunk": yield_decreases,
        "error_delta_largest_minus_smallest": round(largest_vs_smallest_error, 4),
        "entities_raw_delta_smallest_minus_largest": largest_vs_smallest_yield,
        "soft_budget_verdict": verdict,
        "soft_budget_supported": verdict in {"strong", "weak"},
    }


def print_table(rows: list[BudgetRunReport]) -> None:
    header = (
        f"{'chunk':>5} {'budget':>6} {'chunks':>6} {'raw':>5} {'empty%':>7} "
        f"{'mean/ch':>7} {'orphan':>7} {'verbatim':>8} {'error':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in sorted(rows, key=lambda item: item.chunk_size):
        print(
            f"{row.chunk_size:>5} {row.total_budget:>6} {row.chunk_count:>6} "
            f"{row.entities_raw:>5} {row.empty_chunk_rate:>6.1%} "
            f"{row.mean_entities_per_chunk:>7.1f} {row.orphan_rate:>6.1%} "
            f"{row.verbatim_rate:>7.1%} {row.error_score:>7.3f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "input/ZDU_prereqs.txt")
    parser.add_argument("--domain", default="technical")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompts-dir", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--chunk-sizes", type=int, nargs="+", default=[200, 300, 400])
    args = parser.parse_args()

    _, original_config = load_yaml()
    prompt_w = count_prompt_words(args.prompts_dir)
    rows: list[BudgetRunReport] = []

    print(f"Fixed prompt: {prompt_w} words from {args.prompts_dir}")
    print(f"Chunk sweep: {args.chunk_sizes} (recursive, overlap=20%)\n")

    try:
        for chunk_size in args.chunk_sizes:
            print(f"=== chunk_size={chunk_size} (budget={prompt_w + chunk_size}) ===")
            rows.append(validate_one(args.source, args.domain, chunk_size, prompt_w, args.model))
    finally:
        CONFIG_PATH.write_text(original_config, encoding="utf-8")

    analysis = analyze_monotonicity(rows)
    print("\nResults")
    print_table(rows)
    print("\nMonotonicity (increasing chunk size →)")
    print(f"  error_score increases:      {analysis['error_score_increases_with_chunk']}")
    print(f"  empty_chunk_rate increases: {analysis['empty_chunk_rate_increases_with_chunk']}")
    print(f"  entities_raw decreases:     {analysis['entities_raw_decreases_with_chunk']}")
    print(f"  soft budget verdict:        {analysis['soft_budget_verdict']}")
    print(f"  soft budget supported:      {analysis['soft_budget_supported']}")
    print(
        f"  error Δ (400−200 chunk):    {analysis['error_delta_largest_minus_smallest']:+.4f}"
    )
    print(
        f"  yield Δ (200−400 chunk):    {analysis['entities_raw_delta_smallest_minus_largest']:+d} entities"
    )

    payload = {
        "prompt_words": prompt_w,
        "prompts_dir": str(args.prompts_dir),
        "runs": [asdict(row) for row in rows],
        "analysis": analysis,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved to {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
