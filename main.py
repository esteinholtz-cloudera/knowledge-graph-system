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

from src.cli.formatters import print_ontology_status, print_pipeline_summary, print_precheck
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
        print(f"Archiving data/ → {result.archive_path} ...")
        print("  Copied (excluding benchmark.duckdb)")
        print(f"  Updated {result.paths_updated} path(s) in metadata.json")
        print(f"  Updated schema:url in {result.ttl_files_updated} TTL file(s)")
        print("  Cleared data/ and recreated empty subdirectories")
        print("  Restored ontology.ttl to data/ontology/")
        print(f"\nArchive complete: {result.archive_path}")
        print("The benchmark database remains at: data/benchmark.duckdb")

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
            import re as _re
            raw = args.proposal_id
            # Accept full review URLs — extract the trailing UUID/id segment.
            _uuid_match = _re.search(
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                raw,
                _re.I,
            )
            proposal_id = _uuid_match.group(1) if _uuid_match else raw
            if proposal_id != raw:
                print(f"(extracted id from URL: {proposal_id})\n")
            print(json.dumps(ont_svc.diagnose_sub_taxonomy(proposal_id), indent=2))
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
            r = norm_svc.scan(kg, mp, no_llm=args.no_llm)
            print(f"\n  {r.group_count} predicate groups found, {r.review_count} with variants to review")
            print(f"  Written to: {r.map_path}")
            print(f"\nNext: review {r.map_path}, set 'reviewed: true', then run normalize apply")
        elif args.norm_command == "apply":
            try:
                r = norm_svc.apply(kg, ont, mp, dry_run=args.dry_run)
            except (FileNotFoundError, ValueError) as e:
                print(str(e))
                return
            if args.dry_run:
                print("Dry run — showing changes without writing files:")
            verb = "Would rewrite" if r.dry_run else "Rewrote"
            print(f"  {verb} {r.triples} triple(s) in {r.files} file(s)")
            if not r.dry_run:
                print(f"  owl:subPropertyOf declarations added to {ont}")
                n = norm_svc.regenerate_graphs(kg)
                if n:
                    print(f"  Regenerated {n} graph HTML file(s)")
                else:
                    print("  No existing graph HTML files to regenerate (use --with-graph on process)")
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
