#!/usr/bin/env python3
"""Log an LLM-as-judge EE evaluation to the benchmark DuckDB database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.benchmark_store import create_benchmark_store  # noqa: E402

PROMPT_FILES = (
    "entity.system.txt",
    "entity.user.prefix.txt",
    "entity.user.suffix.txt",
)

GRADE_SCORES = {
    "A+": 97,
    "A": 93,
    "A-": 90,
    "B+": 87,
    "B": 83,
    "B-": 80,
    "C+": 77,
    "C": 73,
    "C-": 70,
    "D": 60,
    "F": 50,
}


def load_prompt_bundle(prompts_dir: Path) -> dict[str, str]:
    bundle: dict[str, str] = {}
    for name in PROMPT_FILES:
        path = prompts_dir / name
        if path.is_file():
            bundle[name] = path.read_text(encoding="utf-8")
    return bundle


def grade_score(grade: str) -> float | None:
    normalized = grade.strip().upper().replace(" ", "")
    return GRADE_SCORES.get(normalized)


def lookup_latest_run_id(document_filename: str, llm_model: str) -> str | None:
    bench = create_benchmark_store()
    if not hasattr(bench, "_con"):
        return None
    row = bench._con.execute(
        """
        SELECT run_id
        FROM runs
        WHERE document_filename = ?
          AND llm_model = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        [document_filename, llm_model],
    ).fetchone()
    return row[0] if row else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-id", default=None, help="Update existing row with prompts_after")
    parser.add_argument("--prompts-after-dir", type=Path, default=None)
    parser.add_argument("--markup", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--domain")
    parser.add_argument("--grade")
    parser.add_argument("--summary")
    parser.add_argument("--metrics-file", type=Path)
    parser.add_argument("--prompts-dir", type=Path)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--document-id", default="")
    args = parser.parse_args()

    bench = create_benchmark_store()

    if args.eval_id:
        if not args.prompts_after_dir:
            print("--prompts-after-dir is required with --eval-id", file=sys.stderr)
            return 1
        prompts_after = load_prompt_bundle(args.prompts_after_dir)
        if not prompts_after:
            print(f"No prompt files found in {args.prompts_after_dir}", file=sys.stderr)
            return 1
        bench.update_ee_judge_prompts_after(
            args.eval_id,
            json.dumps({"prompts_dir": str(args.prompts_after_dir), "files": prompts_after}),
        )
        print(args.eval_id)
        return 0

    required = (
        "markup",
        "source",
        "model",
        "domain",
        "grade",
        "summary",
        "metrics_file",
        "prompts_dir",
    )
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        parser.error(f"the following arguments are required: {', '.join('--' + n.replace('_', '-') for n in missing)}")

    metrics = json.loads(args.metrics_file.read_text(encoding="utf-8"))
    prompts_before = load_prompt_bundle(args.prompts_dir)
    if not prompts_before:
        print(f"No prompt files found in {args.prompts_dir}", file=sys.stderr)
        return 1

    document_filename = args.source.name
    run_id = args.run_id or lookup_latest_run_id(document_filename, args.model)

    eval_id = bench.record_ee_judge_evaluation(
        document_filename=document_filename,
        document_id=args.document_id or args.source.stem,
        markup_path=str(args.markup),
        source_path=str(args.source),
        llm_model=args.model,
        domain=args.domain,
        grade=args.grade,
        grade_score=grade_score(args.grade),
        summary=args.summary,
        unique_entities=int(metrics.get("unique_entities", 0)),
        marked_spans=int(metrics.get("marked_spans", 0)),
        orphan_entities=int(metrics.get("orphan_entities", 0)),
        orphan_rate=float(metrics.get("orphan_rate", 0.0)),
        verbatim_issues=int(metrics.get("verbatim_issues", 0)),
        metrics_json=json.dumps(metrics),
        prompts_before=json.dumps({"prompts_dir": str(args.prompts_dir), "files": prompts_before}),
        run_id=run_id,
    )
    print(eval_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
