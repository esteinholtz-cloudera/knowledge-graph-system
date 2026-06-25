#!/usr/bin/env python3
"""Sweep chunk_size (workload) with fixed --max-chunks; compare EE metrics."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[4]
MODEL = "qwen3-30b-a3b-instruct-2507-mlx"
PROMPT_DIR = PROJECT_ROOT / "prompts" / MODEL / "technical"
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
ANALYZE = PROJECT_ROOT / ".cursor/skills/llm-as-judge-ee/scripts/analyze_markup.py"
CONVERGE = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/scripts/check_convergence.py"
THRESHOLDS = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/thresholds-technical.json"


def prompt_words() -> int:
    total = 0
    for name in ("entity.system.txt", "entity.user.prefix.txt", "entity.user.suffix.txt"):
        path = PROMPT_DIR / name
        if path.is_file():
            total += len(path.read_text(encoding="utf-8").split())
    return total


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")


def set_workload(data: dict, chunk_size: int, overlap: int) -> None:
    data["llm"]["model_settings"][MODEL]["chunk_size"] = chunk_size
    data["llm"]["model_settings"][MODEL]["overlap"] = overlap


def run_process(source: Path, domain: str, max_chunks: int) -> None:
    cmd = [
        "uv", "run", "python", "main.py", "process", str(source),
        "--domain", domain, "--max-chunks", str(max_chunks),
    ]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2000:], file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"process failed (exit {result.returncode})")


def measure(markup: Path, source: Path) -> dict:
    metrics_file = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/.sweep_metrics.json"
    with metrics_file.open("w", encoding="utf-8") as fh:
        subprocess.run(
            ["uv", "run", "python", str(ANALYZE), str(markup), str(source), "--json"],
            cwd=PROJECT_ROOT, check=True, stdout=fh,
        )
    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    result = subprocess.run(
        [
            "uv", "run", "python", str(CONVERGE),
            "--metrics-file", str(metrics_file),
            "--markup", str(markup),
            "--thresholds-file", str(THRESHOLDS),
        ],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    convergence = json.loads(result.stdout)
    return {
        "unique_entities": metrics["unique_entities"],
        "marked_spans": metrics["marked_spans"],
        "orphan_rate": convergence["rates"]["orphan_rate"],
        "verbatim_rate": convergence["rates"]["verbatim_rate"],
        "other_rate": convergence["rates"]["other_rate"],
        "generic_hit_rate": convergence["rates"]["generic_hit_rate"],
        "error_score": convergence["rates"]["error_score"],
        "failed_gates": convergence["failed_gates"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "input/ZDU_prereqs.txt")
    parser.add_argument("--domain", default="technical")
    parser.add_argument("--max-chunks", type=int, default=4)
    parser.add_argument("--workloads", type=int, nargs="+", default=[100, 150, 200, 250])
    args = parser.parse_args()

    stem = args.source.stem
    markup = PROJECT_ROOT / "data/documents" / f"{stem}_markup.html"
    prompt_w = prompt_words()
    original = load_config()
    results: list[dict] = []

    try:
        for workload in args.workloads:
            overlap = max(workload // 4, 20)
            cfg = load_config()
            set_workload(cfg, workload, overlap)
            save_config(cfg)
            total = prompt_w + workload
            print(f"\n{'='*60}")
            print(f"workload={workload}  overlap={overlap}  prompt={prompt_w}  budget={total}")
            print(f"{'='*60}")
            run_process(args.source, args.domain, args.max_chunks)
            row = measure(markup, args.source)
            row.update({"workload": workload, "overlap": overlap, "prompt_words": prompt_w, "total_budget": total})
            results.append(row)
            print(
                f"  entities={row['unique_entities']}  orphan={row['orphan_rate']:.1%}  "
                f"verbatim={row['verbatim_rate']:.1%}  error_score={row['error_score']:.3f}"
            )
    finally:
        save_config(original)

    print(f"\n{'='*60}")
    print(f"WORKLOAD SWEEP SUMMARY (--max-chunks={args.max_chunks})")
    print(f"{'='*60}")
    header = f"{'workload':>8} {'overlap':>7} {'budget':>6} {'entities':>8} {'orphan':>7} {'verbatim':>8} {'error':>7}"
    print(header)
    print("-" * len(header))
    best = min(results, key=lambda r: r["error_score"])
    for r in sorted(results, key=lambda x: x["workload"]):
        mark = " <-- best" if r["workload"] == best["workload"] else ""
        print(
            f"{r['workload']:>8} {r['overlap']:>7} {r['total_budget']:>6} "
            f"{r['unique_entities']:>8} {r['orphan_rate']:>6.1%} {r['verbatim_rate']:>7.1%} "
            f"{r['error_score']:>7.3f}{mark}"
        )
    out = PROJECT_ROOT / ".cursor/skills/ee-calibration-loop/.sweep_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nResults saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
