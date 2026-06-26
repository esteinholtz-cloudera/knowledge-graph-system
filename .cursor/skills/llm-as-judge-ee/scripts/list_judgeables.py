#!/usr/bin/env python3
"""List markup outputs available for LLM-as-judge EE evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import load_config  # noqa: E402

INPUT_EXTENSIONS = (".txt", ".md", ".pdf")


def _document_stem(markup_path: Path) -> str:
    name = markup_path.name
    if name.endswith("_markup.html"):
        return name[: -len("_markup.html")]
    return markup_path.stem


def _resolve_source(stem: str, archive_root: Path | None, input_dir: Path) -> Path | None:
    if archive_root is not None:
        meta_path = archive_root / "metadata.json"
        if meta_path.is_file():
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            for doc in data.get("documents", {}).values():
                if doc.get("filename", "").rsplit(".", 1)[0] == stem:
                    path = Path(doc["path"])
                    if path.is_file():
                        return path
                    filename = doc.get("filename")
                    if filename:
                        candidate = input_dir / filename
                        if candidate.is_file():
                            return candidate
    for ext in INPUT_EXTENSIONS:
        candidate = input_dir / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _load_manifest_index() -> dict[str, dict]:
    runs_dir = PROJECT_ROOT / ".cursor" / "skills" / "llm-benchmark" / "runs"
    index: dict[str, dict] = {}
    if not runs_dir.is_dir():
        return index
    for manifest_path in sorted(runs_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        domain = payload.get("domain") or "default"
        for entry in payload.get("runs", []):
            archive_dir = entry.get("archive_dir")
            if not archive_dir or archive_dir in index:
                continue
            index[archive_dir] = {
                "model": entry.get("model"),
                "domain": domain,
                "source": payload.get("source"),
                "manifest": str(manifest_path),
            }
    return index


def _load_benchmark_index() -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    """Return (run_by_doc_model, eval_by_markup)."""
    try:
        from src.storage.benchmark_store import create_benchmark_store
    except ImportError:
        return {}, {}

    bench = create_benchmark_store()
    if not hasattr(bench, "_con"):
        return {}, {}

    run_by_doc_model: dict[tuple[str, str], dict] = {}
    rows = bench._con.execute(
        """
        SELECT run_id, document_filename, llm_model, started_at, run_snapshot_json
        FROM runs
        ORDER BY started_at DESC
        """
    ).fetchall()
    for run_id, document_filename, llm_model, started_at, snapshot_json in rows:
        key = (document_filename, llm_model)
        if key in run_by_doc_model:
            continue
        domain = "default"
        if snapshot_json:
            try:
                domain = json.loads(snapshot_json).get("domain") or domain
            except json.JSONDecodeError:
                pass
        run_by_doc_model[key] = {
            "run_id": run_id,
            "domain": domain,
            "started_at": started_at.isoformat() if started_at else None,
        }

    eval_by_markup: dict[str, dict] = {}
    eval_rows = bench._con.execute(
        """
        SELECT markup_path, grade, recorded_at
        FROM ee_judge_evaluations
        ORDER BY recorded_at DESC
        """
    ).fetchall()
    for markup_path, grade, recorded_at in eval_rows:
        if markup_path not in eval_by_markup:
            eval_by_markup[markup_path] = {
                "grade": grade,
                "evaluated_at": recorded_at.isoformat() if recorded_at else None,
            }
    return run_by_doc_model, eval_by_markup


def _prompt_models() -> list[str]:
    prompts_dir = PROJECT_ROOT / "prompts"
    if not prompts_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in prompts_dir.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )


def _manifest_for_archive(archive_dir: Path, manifest_index: dict[str, dict]) -> dict | None:
    resolved = str(archive_dir.resolve())
    if resolved in manifest_index:
        return manifest_index[resolved]
    name = archive_dir.name
    for key, value in manifest_index.items():
        if Path(key).name == name:
            return value
    if "-" in name:
        base, suffix = name.rsplit("-", 1)
        if suffix.isdigit():
            for key, value in manifest_index.items():
                if Path(key).name == base:
                    return value
    return None


def _model_from_label(label: str, known_models: list[str]) -> str:
    if label in known_models:
        return label
    for model_id in sorted(known_models, key=len, reverse=True):
        sanitized = model_id.replace("/", "_").replace(":", "_").replace(" ", "_")
        if label == sanitized or label.startswith(f"{sanitized}-"):
            return model_id
    if "-" in label:
        base, suffix = label.rsplit("-", 1)
        if suffix.isdigit() and base in known_models:
            return base
    return label


def _resolve_model_domain(
    *,
    archive_label: str,
    document_filename: str,
    configured_model: str,
    configured_models: list[str],
    manifest_index: dict[str, dict],
    run_by_doc_model: dict[tuple[str, str], dict],
    archive_dir: Path | None,
) -> tuple[str, str, str | None]:
    if archive_dir is not None:
        manifest = _manifest_for_archive(archive_dir, manifest_index)
        if manifest and manifest.get("model"):
            domain = manifest.get("domain") or "default"
            run = run_by_doc_model.get((document_filename, manifest["model"]), {})
            return manifest["model"], domain, run.get("run_id")

    known_models = sorted(set(configured_models) | set(_prompt_models()))
    if archive_label == "data":
        model = configured_model
        run = run_by_doc_model.get((document_filename, model), {}) if model else {}
        if not model or not run:
            for (doc_name, llm_model), run_info in run_by_doc_model.items():
                if doc_name == document_filename:
                    model = llm_model
                    run = run_info
                    break
        if not model:
            model = known_models[0] if len(known_models) == 1 else ""
    else:
        model = _model_from_label(archive_label, known_models)
        run = run_by_doc_model.get((document_filename, model), {})

    domain = run.get("domain") or "default"
    return model, domain, run.get("run_id")


def _iter_markup_files() -> list[tuple[Path, str, Path | None]]:
    found: list[tuple[Path, str, Path | None]] = []
    data_markup = PROJECT_ROOT / "data" / "documents"
    if data_markup.is_dir():
        for path in sorted(data_markup.glob("*_markup.html")):
            found.append((path, "data", None))

    for archive_dir in sorted(PROJECT_ROOT.glob("data_save_*")):
        if not archive_dir.is_dir():
            continue
        docs_dir = archive_dir / "documents"
        if not docs_dir.is_dir():
            continue
        label = archive_dir.name.removeprefix("data_save_")
        for path in sorted(docs_dir.glob("*_markup.html")):
            found.append((path, label, archive_dir))
    return found


def list_judgeables(*, include_judged: bool = True) -> dict:
    cfg = load_config(str(PROJECT_ROOT / "config" / "config.yaml"))
    configured_model = cfg.llm.model or ""
    configured_models = sorted(cfg.llm.model_settings.keys())
    input_dir = PROJECT_ROOT / "input"
    manifest_index = _load_manifest_index()
    run_by_doc_model, eval_by_markup = _load_benchmark_index()

    judgeables: list[dict] = []
    for markup_path, archive_label, archive_dir in _iter_markup_files():
        stem = _document_stem(markup_path)
        source_path = _resolve_source(stem, archive_dir, input_dir)
        document_filename = source_path.name if source_path else f"{stem}.txt"

        model, domain, run_id = _resolve_model_domain(
            archive_label=archive_label,
            document_filename=document_filename,
            configured_model=configured_model,
            configured_models=configured_models,
            manifest_index=manifest_index,
            run_by_doc_model=run_by_doc_model,
            archive_dir=archive_dir,
        )

        markup_key = str(markup_path.resolve())
        prior = eval_by_markup.get(markup_key) or eval_by_markup.get(str(markup_path))
        judged = prior is not None
        if judged and not include_judged:
            continue

        mtime = datetime.fromtimestamp(markup_path.stat().st_mtime, tz=timezone.utc)
        judgeables.append(
            {
                "id": f"{archive_label}:{stem}",
                "label": f"{archive_label} / {document_filename} ({model}, {domain})",
                "markup": str(markup_path),
                "source": str(source_path) if source_path else None,
                "model": model,
                "domain": domain,
                "run_id": run_id,
                "archive": archive_label,
                "document_stem": stem,
                "document_filename": document_filename,
                "prompts_dir": str(PROJECT_ROOT / "prompts" / model / domain),
                "source_exists": source_path is not None,
                "markup_mtime": mtime.isoformat(),
                "judged": judged,
                "last_grade": prior.get("grade") if prior else None,
                "last_evaluated_at": prior.get("evaluated_at") if prior else None,
            }
        )

    judgeables.sort(key=lambda item: item["markup_mtime"], reverse=True)
    return {
        "project_root": str(PROJECT_ROOT),
        "count": len(judgeables),
        "include_judged": include_judged,
        "judgeables": judgeables,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--exclude-judged",
        action="store_true",
        help="Omit runs that already have an ee_judge_evaluations row",
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        metavar="ID",
        help="Print only entries matching these ids (e.g. data:ZDU_prereqs)",
    )
    args = parser.parse_args()

    try:
        payload = list_judgeables(include_judged=not args.exclude_judged)
    except Exception as exc:  # noqa: BLE001 — surface discovery errors to CLI
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.ids:
        wanted = set(args.ids)
        payload["judgeables"] = [j for j in payload["judgeables"] if j["id"] in wanted]
        payload["count"] = len(payload["judgeables"])

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Judgeable EE runs ({payload['count']}):")
    for entry in payload["judgeables"]:
        flags = []
        if not entry["source_exists"]:
            flags.append("missing source")
        if entry["judged"]:
            flags.append(f"graded {entry['last_grade']}")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        print(f"  {entry['id']}: {entry['label']}{suffix}")
        print(f"    markup: {entry['markup']}")
        if entry["source"]:
            print(f"    source: {entry['source']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
