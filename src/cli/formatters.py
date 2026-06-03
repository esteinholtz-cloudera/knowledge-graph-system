"""Human-readable CLI output for service results."""
from src.services.models import (
    ArchiveResult,
    NormalizeApplyResult,
    NormalizeScanResult,
    OntologyStatusResult,
    PipelineResult,
    PrecheckResult,
)


def print_precheck(result: PrecheckResult) -> bool:
    print("Pre-flight checks")
    print("─" * 40)
    for check in result.checks:
        name = check.get("name", "")
        ok = check.get("ok", False)
        skipped = check.get("skipped", False)
        msg = check.get("message", "")
        if name in ("llm_model", "llm_endpoint"):
            prefix = "LLM model" if name == "llm_model" else "LLM endpoint"
            sym = "✓" if ok else "✗"
            print(f"  {sym} {prefix + ':':<16} {msg}")
            if not ok and check.get("available"):
                print(f"    Available:      {', '.join(check['available'])}")
        elif name == "embed_model":
            if skipped:
                print(f"  –  Embed model:   ({msg})")
            else:
                sym = "✓" if ok else "✗"
                print(f"  {sym} Embed model:    {msg}")
                if not ok and check.get("available"):
                    print(f"    Available:      {', '.join(check['available'])}")
                    if check.get("hint"):
                        print(f"    Hint: {check['hint']}")
                elif not ok:
                    print(f"  ✗ Embed check failed: {msg}")
        elif name == "resolution":
            if skipped:
                print(f"  –  Resolution:    {msg}")
            else:
                print(f"  ✓ Resolution:     {msg}")
    print("─" * 40)
    if not result.ok:
        print("  Pre-flight FAILED — fix the issues above before running.\n")
    return result.ok


def print_pipeline_summary(result: PipelineResult) -> None:
    print("\n" + "=" * 50)
    print("Processing complete!")
    print("=" * 50)
    print(f"Document ID:    {result.document_id}")
    print(f"Knowledge Graph:{result.kg_path}")
    print(f"HTML Markup:    {result.markup_path}")
    print(f"Entities:       {result.entity_count}")
    print(f"Triples:        {result.triple_count}")
    if result.proposals:
        print(
            f"Ontology proposals: {len(result.proposals)} "
            "(see data/ontology/ontology_proposed.ttl)"
        )


def print_ontology_status(status: OntologyStatusResult) -> None:
    if not status.summary and not status.pending:
        print("No pending ontology proposals.")
        return
    summary = status.summary
    print(f"\nOntology proposals:")
    print(f"  New classes pending:    {summary.get('pending', 0)}")
    print(f"  Entities needing type:  {summary.get('needs_typing', 0)}")
    print(
        f"  Approved: {summary.get('approved', 0)}   "
        f"Rejected: {summary.get('rejected', 0)}"
    )
    if status.pending:
        print(f"\nPending sub-taxonomy proposals:")
        for item in status.pending:
            src = item.get("proposed_by", "")
            label = item.get("label", item.get("id", ""))
            print(f"  • {label}" + (f"  ← {src}" if src else ""))
    if status.needs_typing:
        print(f"\nEntities needing type (sub-taxonomy):")
        for e in status.needs_typing[:10]:
            label = e.get("label", e.get("id", ""))
            source = (e.get("source_ttl") or "").split("/")[-1]
            print(f"  • {label}" + (f"  ← {source}" if source else ""))
        if len(status.needs_typing) > 10:
            print(f"  ... and {len(status.needs_typing) - 10} more")
    if status.pending or status.needs_typing:
        print(f"\nRun: python main.py ontology review")


def print_archive_result(result: ArchiveResult) -> None:
    print(f"Archiving data/ → {result.archive_path} ...")
    print("  Copied (excluding benchmark.duckdb)")
    print(f"  Updated {result.paths_updated} path(s) in metadata.json")
    print(f"  Updated schema:url in {result.ttl_files_updated} TTL file(s)")
    print("  Cleared data/ and recreated empty subdirectories")
    print("  Restored ontology.ttl to data/ontology/")
    print(f"\nArchive complete: {result.archive_path}")
    print("The benchmark database remains at: data/benchmark.duckdb")


def print_normalize_scan(result: NormalizeScanResult, map_path: str) -> None:
    print(f"\n  {result.group_count} predicate groups found, {result.review_count} with variants to review")
    print(f"  Written to: {result.map_path}")
    print(f"\nNext: review {map_path}, set 'reviewed: true', then run normalize apply")


def print_normalize_apply(result: NormalizeApplyResult, ontology_file: str, graphs: int) -> None:
    if result.dry_run:
        print("Dry run — showing changes without writing files:")
    verb = "Would rewrite" if result.dry_run else "Rewrote"
    print(f"  {verb} {result.triples} triple(s) in {result.files} file(s)")
    if not result.dry_run:
        print(f"  owl:subPropertyOf declarations added to {ontology_file}")
        if graphs:
            print(f"  Regenerated {graphs} graph HTML file(s)")
        else:
            print("  No existing graph HTML files to regenerate (use --with-graph on process)")
