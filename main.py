"""Main CLI entry point for knowledge graph system."""
import sys
from pathlib import Path

# Re-exec with the project virtualenv if we were launched with the system Python.
# This catches the common mistake of running `python main.py ...` instead of
# `.venv/bin/python main.py ...` (which produces ModuleNotFoundError for yaml,
# rdflib, etc.).
_HERE = Path(__file__).resolve().parent
_VENV_PYTHON = _HERE / ".venv" / "bin" / "python"
if _VENV_PYTHON.exists() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    import os
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv)

import argparse

from src.cli.formatters import (
    print_archive_result,
    print_normalize_apply,
    print_normalize_scan,
    print_ontology_status,
    print_pipeline_summary,
    print_precheck,
)
from src.config.settings import load_config
from src.extraction.entity_extractor import ExtractionError
from src.services import (
    ArchiveService,
    BenchmarkService,
    CliProgressReporter,
    HealthService,
    NormalizeService,
    OntologyService,
    PipelineOptions,
    PipelineService,
)

_PROJECT_ROOT = Path(__file__).parent


def _collect_upgrade_sources(args) -> list:
    """Assemble source URLs/files from sitemap, --url, --urls-file, --input."""
    from src.extraction.upgrade.runner import scope

    sources = list(args.url) + list(args.input)
    if args.urls_file:
        text = Path(args.urls_file).read_text(encoding="utf-8")
        sources += [line.strip() for line in text.splitlines() if line.strip()]
    if args.sitemap:
        sources += scope(args.sitemap, limit=args.limit)
    return list(dict.fromkeys(sources))


def _run_upgrade(args) -> None:
    from src.extraction.upgrade import run_upgrade_extraction
    from src.extraction.upgrade.runner import scope

    if args.up_command == "scope":
        urls = scope(args.sitemap, limit=args.limit)
        if args.out:
            Path(args.out).write_text("\n".join(urls) + "\n", encoding="utf-8")
            print(f"Wrote {len(urls)} upgrade-relevant URL(s) to {args.out}")
        else:
            print("\n".join(urls))
            print(f"\n{len(urls)} upgrade-relevant URL(s)")
        return

    if args.up_command != "extract":
        print("Usage: upgrade {scope|extract} ...")
        return

    sources = _collect_upgrade_sources(args)
    if not sources:
        print("No sources. Provide --sitemap, --url, --urls-file, or --input.")
        sys.exit(1)
    print(f"Funnel input: {len(sources)} source(s). LLM: {'off' if args.no_llm else 'on'}")
    result = run_upgrade_extraction(sources, args.output, use_llm=not args.no_llm)
    print(
        f"Pages processed: {result.pages} (skipped {result.skipped_duplicates} duplicate(s))\n"
        f"Chunks: {result.chunks_gated} sent to LLM of {result.chunks_total} total "
        f"({result.chunks_total - result.chunks_gated} gated out, zero tokens)\n"
        f"Facts: {result.fact_count} total — {result.table_facts} from tables, "
        f"{result.llm_facts} from LLM (pre-dedupe)\n"
        f"TTL written to: {result.output_path}"
    )


def main():
    parser = argparse.ArgumentParser(description="Knowledge Graph System")
    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser("process", help="Process a document")
    p.add_argument("file_path")
    p.add_argument("--output-dir", default="data/knowledge_graphs")
    p.add_argument("--max-chunks", type=int, default=None, help="Limit chunks (testing)")
    p.add_argument("--with-graph", action="store_true", help="Generate graph HTML")
    p.add_argument("--domain", default="default", help="Extraction domain profile")

    server_cfg = load_config(str(_PROJECT_ROOT / "config" / "config.yaml")).n8n
    s = subparsers.add_parser("server", help="Start n8n API server")
    s.add_argument("--host", default=server_cfg.host)
    s.add_argument("--port", type=int, default=server_cfg.port)
    s.add_argument("--debug", action="store_true")

    arc_p = subparsers.add_parser("archive", help="Archive data/ and reset")
    arc_p.add_argument("--name", default=None)
    arc_p.add_argument("--llmnamed", action="store_true")

    ont_p = subparsers.add_parser("ontology", help="Ontology management")
    ont_sub = ont_p.add_subparsers(dest="ont_command")
    ont_sub.add_parser("approve")
    ont_sub.add_parser("review")
    ont_sub.add_parser("status")
    ont_sub.add_parser("visualize")
    ont_diag = ont_sub.add_parser("diagnose", help="Explain why a SubTaxonomyProposal id cannot be loaded")
    ont_diag.add_argument(
        "proposal_id",
        help="UUID or full review URL (http://…/ontology/review/<uuid>) — the UUID is extracted automatically",
    )

    norm_p = subparsers.add_parser("normalize", help="Predicate normalization")
    norm_sub = norm_p.add_subparsers(dest="norm_command")
    norm_scan = norm_sub.add_parser("scan")
    norm_scan.add_argument("--no-llm", action="store_true")
    norm_review = norm_sub.add_parser("review")
    norm_apply = norm_sub.add_parser("apply")
    norm_apply.add_argument("--dry-run", action="store_true")
    for p_ in (norm_scan, norm_review, norm_apply):
        p_.add_argument("--kg-dir", default="data/knowledge_graphs")
        p_.add_argument("--ontology-file", default="data/ontology/ontology.ttl")
        p_.add_argument("--map-file", default="data/predicate_map.yaml")

    bm_p = subparsers.add_parser("benchmark", help="Benchmark metrics")
    bm_sub = bm_p.add_subparsers(dest="bm_command")
    bm_show = bm_sub.add_parser("show")
    bm_show.add_argument("view", nargs="?", default="runs", choices=["runs", "chunks", "llm"])
    bm_query = bm_sub.add_parser("query")
    bm_query.add_argument("sql")
    bm_sub.add_parser("clear")

    up_p = subparsers.add_parser(
        "upgrade",
        help="Token-conservative extraction of product upgrade facts into TTL",
    )
    up_sub = up_p.add_subparsers(dest="up_command")
    up_scope = up_sub.add_parser("scope", help="List upgrade-relevant URLs from a sitemap")
    up_scope.add_argument("--sitemap", required=True, help="Sitemap (or sitemap-index) URL")
    up_scope.add_argument("--limit", type=int, default=0, help="Cap number of URLs (0 = all)")
    up_scope.add_argument("--out", default=None, help="Write URLs to this file (one per line)")

    up_ext = up_sub.add_parser("extract", help="Run the upgrade funnel and write TTL")
    up_ext.add_argument("--sitemap", default=None, help="Scope sources from this sitemap URL")
    up_ext.add_argument("--limit", type=int, default=0, help="Cap sitemap-scoped URLs (0 = all)")
    up_ext.add_argument("--url", action="append", default=[], help="Source URL (repeatable)")
    up_ext.add_argument("--urls-file", default=None, help="File of source URLs (one per line)")
    up_ext.add_argument("--input", action="append", default=[], help="Local HTML/text file (repeatable)")
    up_ext.add_argument("--no-llm", action="store_true", help="Deterministic tables only (zero tokens)")
    up_ext.add_argument("--output", default="data/knowledge_graphs/upgrade.ttl")

    args = parser.parse_args()

    if args.command == "process":
        if not print_precheck(HealthService().check()):
            sys.exit(1)
        try:
            result = PipelineService(_PROJECT_ROOT).run(
                PipelineOptions(
                    file_path=args.file_path,
                    output_dir=args.output_dir,
                    max_chunks=args.max_chunks,
                    with_graph=args.with_graph,
                    domain=args.domain,
                ),
                CliProgressReporter(),
            )
        except ExtractionError:
            sys.exit(1)
        print_pipeline_summary(result)

    elif args.command == "server":
        from src.api.app import create_app
        debug = args.debug or server_cfg.debug
        create_app(_PROJECT_ROOT).run(host=args.host, port=args.port, debug=debug)

    elif args.command == "archive":
        try:
            result = ArchiveService(_PROJECT_ROOT).create(name=args.name, llmnamed=args.llmnamed)
        except FileExistsError as e:
            print(str(e))
            sys.exit(1)
        print_archive_result(result)

    elif args.command == "ontology":
        ont_svc = OntologyService(_PROJECT_ROOT)
        if args.ont_command == "approve":
            r = ont_svc.approve()
            if r.approved_count == 0:
                print("No proposed ontology file found. Nothing to approve.")
            else:
                print(f"Approved {r.approved_count} new class(es). ontology.ttl updated.")
        elif args.ont_command == "status":
            print_ontology_status(ont_svc.status())
        elif args.ont_command == "review":
            try:
                from src.extraction.llm_client import LLMClient
                LLMClient.from_config()
            except Exception:
                print("Warning: LLM not available — placement proposals will be limited.")
            ont_svc.run_interactive_review()
        elif args.ont_command == "visualize":
            if ont_svc.visualize() is None:
                print("ontology.ttl not found.")
        elif args.ont_command == "diagnose":
            import json
            result = ont_svc.diagnose_sub_taxonomy(args.proposal_id)
            if note := result.pop("_url_extracted", None):
                print(f"(extracted id from URL: {note})\n")
            print(json.dumps(result, indent=2))
        else:
            ont_p.print_help()

    elif args.command == "normalize":
        norm_svc = NormalizeService(_PROJECT_ROOT)
        kg = str(_PROJECT_ROOT / args.kg_dir)
        ont = str(_PROJECT_ROOT / args.ontology_file)
        mp = str(_PROJECT_ROOT / args.map_file)
        if args.norm_command == "scan":
            print(f"Scanning {kg} for predicates...")
            if not args.no_llm:
                try:
                    from src.extraction.llm_client import LLMClient
                    LLMClient.from_config()
                    print("  LLM available — will suggest canonical mappings")
                except Exception:
                    print("  LLM unavailable — using string similarity only")
            print_normalize_scan(norm_svc.scan(kg, mp, no_llm=args.no_llm), mp)
        elif args.norm_command == "apply":
            try:
                r = norm_svc.apply(kg, ont, mp, dry_run=args.dry_run)
            except (FileNotFoundError, ValueError) as e:
                print(str(e))
                return
            n = norm_svc.regenerate_graphs(kg) if not r.dry_run else 0
            print_normalize_apply(r, ont, n)
        elif args.norm_command == "review":
            norm_svc.run_interactive_review(mp)
        else:
            norm_p.print_help()

    elif args.command == "benchmark":
        bm = BenchmarkService()
        if args.bm_command == "show":
            print(bm.show(view=args.view).text)
        elif args.bm_command == "query":
            print(bm.show(sql=args.sql).text)
        elif args.bm_command == "clear":
            bm.clear()
            print("Benchmark data cleared.")
        else:
            bm_p.print_help()

    elif args.command == "upgrade":
        if args.up_command:
            _run_upgrade(args)
        else:
            up_p.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
