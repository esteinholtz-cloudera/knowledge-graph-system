#!/usr/bin/env python3
"""Report per-chunk yield and prompt/chunk budget for the latest benchmark run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import load_config
from src.storage.benchmark_store import create_benchmark_store
from src.storage.yield_metrics import (
    budget_report,
    chunk_yield_stats,
    latest_run_id,
    prompt_words,
    yield_regression,
)

DEFAULT_MODEL = "qwen3-30b-a3b-instruct-2507-mlx"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", required=True, help="Source filename, e.g. ZDU_prereqs.txt")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=PROJECT_ROOT / "prompts" / DEFAULT_MODEL / "technical",
    )
    parser.add_argument("--previous-run-id", help="Prior run to detect yield regression")
    parser.add_argument("--run-id", help="Benchmark run (default: latest for doc+model)")
    args = parser.parse_args()

    bench = create_benchmark_store()
    if not hasattr(bench, "_con"):
        print("Benchmark store unavailable", file=sys.stderr)
        return 1

    run_id = args.run_id or latest_run_id(bench, args.document, args.model)
    stats = chunk_yield_stats(run_id, bench)

    previous = None
    if args.previous_run_id:
        previous = chunk_yield_stats(args.previous_run_id, bench)
    bench.close()

    cfg = load_config().llm.for_model(args.model)
    prompt_w = prompt_words(args.prompts_dir)
    report = budget_report(
        prompt_words=prompt_w,
        chunk_size=cfg.chunk_size,
        chunk_strategy=cfg.chunk_strategy,
        yield_stats=stats,
    )
    report["regression"] = yield_regression(stats, previous)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
