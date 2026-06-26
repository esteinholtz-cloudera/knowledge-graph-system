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
from src.config.settings import (
    ConfigOverrideError,
    DomainSettings,
    add_override_arg,
    apply_cli_overrides,
    load_config,
)
from src.extraction.entity_extractor import ExtractionError
from src.extraction.prompt_store import FALLBACK_MODEL, PromptStore
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

    def _on_progress(p) -> None:
        print(
            f"[{p.index}/{p.total}] {p.status}: {p.source} "
            f"(facts so far: {p.fact_count}, saved to {args.output})"
        )

    result = run_upgrade_extraction(
        sources, args.output, use_llm=not args.no_llm,
        on_progress=_on_progress, resume=not args.restart,
    )
    print(
        f"Pages processed: {result.pages} "
        f"(skipped {result.skipped_duplicates} duplicate(s), "
        f"{result.already_done} already done)\n"
        f"Chunks: {result.chunks_gated} sent to LLM of {result.chunks_total} total "
        f"({result.chunks_total - result.chunks_gated} gated out, zero tokens)\n"
        f"Facts: {result.fact_count} total in TTL — {result.table_facts} from tables, "
        f"{result.llm_facts} from LLM this run (pre-dedupe)\n"
        f"TTL written to: {result.output_path}\n"
        f"Progress manifest: {result.manifest_path or '(none)'}"
    )


def main():
    parent = argparse.ArgumentParser(add_help=False)
    add_override_arg(parent)

    parser = argparse.ArgumentParser(
        description="Knowledge Graph System",
        parents=[parent],
    )
    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser("process", help="Process a document")
    p.add_argument("file_path")
    p.add_argument("--output-dir", default="data/knowledge_graphs")
    p.add_argument("--max-chunks", type=int, default=None, help="Limit chunks (testing)")
    p.add_argument("--with-graph", action="store_true", help="Generate graph HTML")
    p.add_argument("--domain", default="default", help="Extraction domain profile")

    s = subparsers.add_parser("server", help="Start n8n API server")
    s.add_argument("--host", default=None, help="Default: n8n.host from config")
    s.add_argument("--port", type=int, default=None, help="Default: n8n.port from config")
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
    bm_restore = bm_sub.add_parser(
        "restore-run",
        help="Restore prompt files and show chunk settings from a stored run snapshot",
    )
    bm_restore.add_argument("run_id", help="run_id from benchmark runs table")

    pr_p = subparsers.add_parser("prompts", help="Manage extraction prompt files")
    pr_sub = pr_p.add_subparsers(dest="pr_command")
    pr_reg = pr_sub.add_parser(
        "regenerate",
        help="Write concrete prompt instances to prompts/{model}/{domain}/",
    )
    pr_reg.add_argument("--model", default=None, help="Model name (default: _default)")
    pr_reg.add_argument("--domain", default=None, help="Domain profile (default: default)")
    pr_reg.add_argument(
        "--all",
        action="store_true",
        help="Regenerate _default + all model_settings models and all domains",
    )
    pr_reg.add_argument("--force", action="store_true", help="Overwrite existing prompt files")
    pr_list = pr_sub.add_parser("list", help="List prompt instances on disk")
    pr_list.add_argument("--model", default=None, help="Filter to one model directory")

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
    up_ext.add_argument("--restart", action="store_true", help="Ignore saved progress; start a fresh run")
    up_ext.add_argument("--output", default="data/knowledge_graphs/upgrade.ttl")

    args = parser.parse_args()
    try:
        apply_cli_overrides(args.config_set, str(_PROJECT_ROOT / "config" / "config.yaml"))
    except ConfigOverrideError as e:
        raise SystemExit(str(e)) from e

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
        n8n = load_config(str(_PROJECT_ROOT / "config" / "config.yaml")).n8n
        host = args.host if args.host is not None else n8n.host
        port = args.port if args.port is not None else n8n.port
        debug = args.debug or n8n.debug
        create_app(_PROJECT_ROOT).run(host=host, port=port, debug=debug)

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
        elif args.bm_command == "restore-run":
            try:
                result = bm.restore_run(args.run_id, _PROJECT_ROOT)
            except ValueError as e:
                print(str(e))
                sys.exit(1)
            snap = result["snapshot"]
            print(f"Restored prompts to {result['prompts_dir']}")
            print(
                f"Run settings: domain={snap['domain']} "
                f"chunk_size={snap['chunk_size']} overlap={snap['overlap']} "
                f"section_size={snap['section_size']}"
            )
            print("Update config.yaml model_settings to match chunk_size/overlap before re-running.")
        else:
            bm_p.print_help()

    elif args.command == "upgrade":
        if args.up_command:
            _run_upgrade(args)
        else:
            up_p.print_help()
    elif args.command == "prompts":
        store = PromptStore(_PROJECT_ROOT)
        config = load_config(str(_PROJECT_ROOT / "config" / "config.yaml"))
        domain_settings = {"default": DomainSettings(), **config.domains}

        if args.pr_command == "regenerate":
            if args.all:
                models = [FALLBACK_MODEL, *sorted(config.llm.model_settings.keys())]
                domains = ["default", *sorted(config.domains.keys())]
            else:
                models = [args.model or FALLBACK_MODEL]
                domains = [args.domain or "default"]
            results = store.regenerate(
                models,
                domains,
                config.llm,
                domain_settings,
                force=args.force,
            )
            total = sum(len(paths) for by_domain in results.values() for paths in by_domain.values())
            if total == 0:
                print("No prompt files written (already exist — use --force to overwrite).")
            else:
                for model, by_domain in results.items():
                    for domain, paths in by_domain.items():
                        for path in paths:
                            print(f"  wrote {path.relative_to(_PROJECT_ROOT)}")
                print(
                    f"\nWrote {total} prompt file(s). Edit under prompts/{{model}}/{{domain}}/, "
                    "then run process as usual."
                )
        elif args.pr_command == "list":
            models = [args.model] if args.model else store.list_models()
            if not models:
                print("No prompt files found. Run: python main.py prompts regenerate --all")
            else:
                for model in models:
                    domains = store.list_domains(model)
                    if not domains:
                        continue
                    print(f"{model}/")
                    for domain in domains:
                        print(f"  {domain}/")
                        for path in store.list_files(model, domain):
                            print(f"    {path.name}")
        else:
            pr_p.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
