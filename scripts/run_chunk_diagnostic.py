#!/usr/bin/env python3
"""Triggered diagnostic: same prompt, smaller chunk — disambiguate budget vs content."""
from __future__ import annotations

import argparse
import json
import subprocess
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
)

DEFAULT_MODEL = "qwen3-30b-a3b-instruct-2507-mlx"
CONFIG_PATH = PROJECT_ROOT / "config/config.yaml"


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


def apply_chunk_size(chunk_size: int, overlap: int, model: str) -> None:
    config, _ = load_yaml()
    llm = config.setdefault("llm", {})
    llm["chunk_strategy"] = "recursive"
    llm["chunk_size"] = chunk_size
    llm["overlap"] = overlap
    model_cfg = llm.setdefault("model_settings", {}).setdefault(model, {})
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


def diagnostic_chunk_size(current: int) -> int:
    return max(int(current * 0.67), 150)


def overlap_for(chunk_size: int) -> int:
    return max(chunk_size // 5, 20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--domain", default="technical")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=PROJECT_ROOT / "prompts" / DEFAULT_MODEL / "technical",
    )
    parser.add_argument(
        "--baseline-run-id",
        help="Run before regression (default: latest before diagnostic)",
    )
    args = parser.parse_args()

    cfg = load_config().llm.for_model(args.model)
    smaller = diagnostic_chunk_size(cfg.chunk_size)
    overlap = overlap_for(smaller)

    bench = create_benchmark_store()
    baseline_run_id = args.baseline_run_id or latest_run_id(
        bench, args.source.name, args.model,
    )
    baseline = chunk_yield_stats(baseline_run_id, bench)
    bench.close()

    _, original_config = load_yaml()
    print(
        f"Diagnostic: chunk {cfg.chunk_size} → {smaller} "
        f"(prompt fixed at {prompt_words(args.prompts_dir)}w)"
    )

    try:
        apply_chunk_size(smaller, overlap, args.model)
        run_extraction(args.source, args.domain)
    finally:
        CONFIG_PATH.write_text(original_config, encoding="utf-8")

    bench = create_benchmark_store()
    diagnostic_run_id = latest_run_id(bench, args.source.name, args.model)
    diagnostic = chunk_yield_stats(diagnostic_run_id, bench)
    bench.close()

    prompt_w = prompt_words(args.prompts_dir)
    baseline_report = budget_report(
        prompt_words=prompt_w,
        chunk_size=cfg.chunk_size,
        chunk_strategy=cfg.chunk_strategy,
        yield_stats=baseline,
    )
    diagnostic_report = budget_report(
        prompt_words=prompt_w,
        chunk_size=smaller,
        chunk_strategy="recursive",
        yield_stats=diagnostic,
    )

    retention = (
        diagnostic.entities_raw / baseline.entities_raw
        if baseline.entities_raw > 0
        else 1.0
    )
    recovered = (
        retention >= 0.85
        and diagnostic.empty_chunk_rate <= baseline.empty_chunk_rate + 0.05
    ) or diagnostic.entities_raw > baseline.entities_raw

    payload = {
        "baseline": baseline_report,
        "diagnostic": diagnostic_report,
        "entities_raw_retention": round(retention, 4),
        "yield_recovered_at_smaller_chunk": recovered,
        "attribution": "budget_dilution" if recovered else "prompt_content",
        "recommendation": (
            "Shrink chunk_size or trim prompt before adding rules."
            if recovered
            else "Revert or soften restrictive prompt phrasing; chunk size is not the binding limit."
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
