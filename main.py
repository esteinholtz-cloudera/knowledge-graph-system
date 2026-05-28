"""Main CLI entry point for knowledge graph system."""
import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from src.config.settings import load_config
from src.document.processor import DocumentProcessor
from src.document.html_markup import HTMLMarkupGenerator
from src.extraction.entity_extractor import EntityExtractor, ExtractionError
from src.extraction.entity_resolver import EntityResolver
from src.extraction.relationship_extractor import RelationshipExtractor
from src.storage.benchmark_store import create_benchmark_store, BenchmarkStore
from src.storage.turtle_writer import TurtleWriter
from src.storage.metadata_store import MetadataStore

_PROJECT_ROOT = Path(__file__).parent


def run_precheck() -> bool:
    """
    Verify that configured LLM and optional embedding model are reachable.
    Prints a status summary and returns True if all required services are available.
    """
    import httpx
    from src.config.settings import load_config

    app = load_config()
    llm = app.llm
    res = app.entity_resolution
    base_url = llm.resolved_base_url()
    all_ok = True

    print("Pre-flight checks")
    print("─" * 40)

    # 1. LLM endpoint reachable + model listed
    try:
        headers = {}
        if llm.get_api_key():
            headers["Authorization"] = f"Bearer {llm.get_api_key()}"
        resp = httpx.get(f"{base_url}/models", headers=headers, timeout=8)
        resp.raise_for_status()
        available = [m["id"] for m in resp.json().get("data", [])]
        if llm.model is None:
            # Auto-detect: use first available
            if available:
                print(f"  ✓ LLM model:      {available[0]} (auto-detected)")
            else:
                print(f"  ✗ LLM model:      no models available at {base_url}")
                all_ok = False
        elif llm.model in available:
            print(f"  ✓ LLM model:      {llm.model}")
        else:
            print(f"  ✗ LLM model:      {llm.model!r} NOT found at {base_url}")
            print(f"    Available:      {', '.join(available)}")
            all_ok = False
    except Exception as e:
        print(f"  ✗ LLM endpoint:   {base_url} unreachable ({e})")
        all_ok = False

    # 2. Embedding model (only if resolution.embedding strategy is active)
    if res.enabled and "embedding" in res.strategies:
        try:
            resp = httpx.get(f"{base_url}/models", headers=headers, timeout=8)
            available = [m["id"] for m in resp.json().get("data", [])]
            if res.embedding_model in available:
                print(f"  ✓ Embed model:    {res.embedding_model}")
            else:
                print(f"  ✗ Embed model:    {res.embedding_model!r} NOT found")
                print(f"    Available:      {', '.join(available)}")
                print(f"    Hint: load it in LM Studio or update embedding_model in config.yaml")
                all_ok = False
        except Exception as e:
            print(f"  ✗ Embed check failed: {e}")
            all_ok = False
    elif res.enabled:
        print(f"  –  Embed model:   (not used — strategies: {res.strategies})")

    # 3. Entity resolution status
    if res.enabled:
        print(f"  ✓ Resolution:     enabled ({', '.join(res.strategies)}, threshold={res.embedding_threshold})")
    else:
        print(f"  –  Resolution:    disabled")

    print("─" * 40)
    if not all_ok:
        print("  Pre-flight FAILED — fix the issues above before running.\n")
    return all_ok


def generate_graph_html(ttl_path: str, graph_html_path: str) -> Optional[str]:
    """
    Run ttl_to_html.py from the ai-knowledge-graph project to produce an
    interactive graph visualisation. Returns the output path or None on failure.
    """
    import subprocess

    app_config = load_config()
    ai_kg_path = app_config.visualization.resolved_ai_kg_path()
    if not ai_kg_path:
        print("  ✗ Graph skipped — ai-knowledge-graph not found. Set visualization.ai_kg_path in config.yaml")
        return None

    script = Path(ai_kg_path) / "ttl_to_html.py"
    python = Path(ai_kg_path) / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path("python3")

    print(f"  Generating graph visualisation...")
    result = subprocess.run(
        [str(python), str(script), ttl_path, graph_html_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ✗ Graph generation failed:\n{result.stderr.strip()}")
        return None

    # Print stats line from the script output
    for line in result.stdout.splitlines():
        if "Nodes:" in line or "Edges:" in line or "Communities:" in line:
            print(f"    {line.strip()}")

    print(f"  Graph HTML saved to: {graph_html_path}")
    return graph_html_path


def process_and_extract(file_path: str, output_dir: str = "data/knowledge_graphs", max_chunks: int = None, with_graph: bool = False):
    """Process a document and extract knowledge graph."""
    run_start = time.monotonic()
    print(f"Processing document: {file_path}")

    app_config = load_config()

    # Build extractors first so the model name is resolved (auto-detect fires here).
    # The resolved model name is needed to apply per-model config overrides (chunk_size, etc.).
    entity_extractor = EntityExtractor()
    relationship_extractor = RelationshipExtractor()
    resolved_model = entity_extractor.llm_client._provider.model

    # Apply per-model overrides to get the effective LLM config for this run.
    llm_cfg = app_config.llm.for_model(resolved_model)

    processor = DocumentProcessor(
        chunk_size=llm_cfg.chunk_size,
        overlap=llm_cfg.overlap,
    )
    doc_data = processor.process_document(file_path)
    document_id = Path(doc_data['filename']).stem  # e.g. "Skills_description"

    print(f"Document:   {doc_data['filename']}")
    print(f"Word count: {doc_data['word_count']}")

    chunks = processor.chunk_text(doc_data['text'])
    if max_chunks and len(chunks) > max_chunks:
        print(f"Split into {len(chunks)} chunks (limiting to first {max_chunks})")
        chunks = chunks[:max_chunks]
    else:
        print(f"Split into {len(chunks)} chunks")

    # Open benchmark DB and start run record (no-op if duckdb not installed)
    bench = create_benchmark_store()
    run_id = bench.start_run(
        document_filename=doc_data['filename'],
        document_id=document_id,
        word_count=doc_data['word_count'],
        llm_provider=app_config.llm.provider,
        llm_model=resolved_model,
        resolution_enabled=app_config.entity_resolution.enabled,
        resolution_strategies=list(app_config.entity_resolution.strategies),
        max_chunks=max_chunks,
    )

    total_chunks = len(chunks)
    chunk_times: list = []

    # ── Pass 1: entity extraction across all chunks ───────────────────────
    print(f"\n{'═' * 50}")
    print(f"  Pass 1 of 2 — Entity extraction")
    print(f"  ({total_chunks} chunk(s) × {llm_cfg.chunk_size} words)")
    print(f"{'═' * 50}")
    all_entities = []
    chunk_entity_counts = []

    for i, chunk in enumerate(chunks):
        chunk_num = i + 1
        if chunk_times:
            avg = sum(chunk_times) / len(chunk_times)
            remaining = avg * (total_chunks - i)
            m, s = divmod(int(remaining), 60)
            eta_str = f"  ETA ~{m}m{s:02d}s" if m else f"  ETA ~{s}s"
        else:
            eta_str = ""

        print(f"\n{'─' * 50}")
        print(f"  Chunk {chunk_num}/{total_chunks}{eta_str}")
        print(f"{'─' * 50}")
        t0 = time.monotonic()

        try:
            entities = entity_extractor.extract(
                chunk,
                progress_label=f"chunk {chunk_num}/{total_chunks} · entities",
            )
        except ExtractionError as exc:
            bench.close()
            print(f"\n{'═' * 50}")
            print(f"  EXTRACTION ERROR — chunk {chunk_num}/{total_chunks}")
            print(f"{'═' * 50}")
            print(str(exc))
            print("\nHints:")
            print("  • Set disable_thinking: true in config.yaml for thinking models")
            print("  • Try a different model or adjust the entity extraction prompt")
            print("  • Use --max-chunks 1 to isolate which chunk fails")
            sys.exit(1)
        elapsed = time.monotonic() - t0
        bench.record_llm_call(run_id, "entity_extraction", elapsed, chunk_number=chunk_num)
        all_entities.extend(entities)
        chunk_entity_counts.append(len(entities))
        chunk_times.append(elapsed)
        print(f"  ✓ Entities: {len(entities)}  ({elapsed:.1f}s)")

    # Deduplicate entities using case-insensitive key so HAMLET, HAmlet, hamlet
    # all collapse to the same canonical entry. Keep track of raw variants as
    # alternate_names. Prefer title-case form; fall back to first non-all-caps seen.
    _ci: dict = {}  # lowercase_key → entity dict
    def _best_form(name: str) -> str:
        """Return the best canonical display form for a name.
        - ALL_CAPS proper names (4+ chars): Title Case  (HAMLET → Hamlet)
        - ALL_CAPS abbreviations (< 4 chars): keep   (LLM, RAG)
        - mixed-case / already title: keep as-is
        """
        if name.isupper() and len(name) >= 4:
            return name.title()
        return name

    def _form_rank(name: str) -> int:
        """Higher = better canonical form.
        mixed-case (Hamlet, LLM) = 1 > all-lowercase (hamlet) = 0.
        """
        return 0 if name == name.lower() else 1

    for entity in all_entities:
        name = entity.get('entity', '')
        if not name:
            continue
        key = name.lower()
        canonical = _best_form(name)
        existing = _ci.get(key)
        if existing is None:
            _ci[key] = {**entity, 'entity': canonical, 'alternate_names': set()}
        else:
            current = existing['entity']
            # Upgrade to better display form if available
            if _form_rank(canonical) > _form_rank(current):
                existing['alternate_names'].add(current)
                existing['entity'] = canonical
            # Prefer non-Other type
            if existing.get('type', 'Other') == 'Other' and entity.get('type', 'Other') != 'Other':
                existing['type'] = entity['type']
        # Record raw name as alternate if it differs from the stored canonical
        if _ci[key]['entity'] != name:
            _ci[key]['alternate_names'].add(name)

    # Convert alternate_names sets to sorted lists for determinism
    unique_entities: dict = {}
    for entry in _ci.values():
        entry['alternate_names'] = sorted(entry['alternate_names'])
        unique_entities[entry['entity']] = entry

    entities_raw = len(unique_entities)
    print(f"\nTotal unique entities (raw): {entities_raw}")

    if app_config.entity_resolution.enabled:
        print(f"\nRunning entity resolution ({', '.join(app_config.entity_resolution.strategies)})...")
        t0 = time.monotonic()
        resolver = EntityResolver(app_config.entity_resolution, llm_client=None)
        resolved_list = resolver.resolve(list(unique_entities.values()))
        unique_entities = {e['entity']: e for e in resolved_list}
        bench.record_resolution(
            run_id, "+".join(app_config.entity_resolution.strategies),
            entities_before=entities_raw,
            entities_after=len(unique_entities),
            elapsed_s=time.monotonic() - t0,
        )
        print(f"  After resolution: {len(unique_entities)} entities")

    # Canonical entity names to feed to relationship extractor
    canonical_names = list(unique_entities.keys())
    # Case-insensitive lookup: includes canonical names AND their alternate names
    canonical_lookup = {name.lower(): name for name in canonical_names}
    for entity in unique_entities.values():
        for alt in entity.get('alternate_names', []):
            canonical_lookup[alt.lower()] = entity['entity']

    # ── Pass 2: relationship extraction using canonical entity names ───────
    print(f"\n{'═' * 50}")
    print(f"  Pass 2 of 2 — Relationship extraction  (per-chunk)")
    print(f"{'═' * 50}")
    all_triples_set: set = set()
    all_triples = []
    chunk_times = []

    for i, chunk in enumerate(chunks):
        chunk_num = i + 1
        if chunk_times:
            avg = sum(chunk_times) / len(chunk_times)
            remaining = avg * (total_chunks - i)
            m, s = divmod(int(remaining), 60)
            eta_str = f"  ETA ~{m}m{s:02d}s" if m else f"  ETA ~{s}s"
        else:
            eta_str = ""

        print(f"\n{'─' * 50}")
        print(f"  Chunk {chunk_num}/{total_chunks}{eta_str}")
        print(f"{'─' * 50}")
        chunk_start = time.monotonic()

        t0 = time.monotonic()
        triples = relationship_extractor.extract(
            chunk,
            canonical_names,   # resolved, canonical names
            progress_label=f"chunk {chunk_num}/{total_chunks} · relationships",
        )
        elapsed_llm = time.monotonic() - t0
        bench.record_llm_call(run_id, "relationship_extraction", elapsed_llm, chunk_number=chunk_num)

        for t in triples:
            # Correct subject/object to canonical form where possible
            subj = t.get('subject', '')
            obj = t.get('object', '')
            canonical_subj = canonical_lookup.get(subj.lower(), subj)
            canonical_obj = canonical_lookup.get(obj.lower(), obj)
            t = {**t, 'subject': canonical_subj, 'object': canonical_obj}

            key = (t['subject'], t.get('predicate', ''), t['object'])
            if key not in all_triples_set:
                all_triples_set.add(key)
                all_triples.append(t)

        elapsed = time.monotonic() - chunk_start
        chunk_times.append(elapsed)
        print(f"  ✓ Relationships: {len(triples)}  ({elapsed:.1f}s)")
        bench.record_chunk(
            run_id, chunk_num,
            word_count=len(chunk.split()),
            entities=chunk_entity_counts[i],
            relationships=len(triples),
            elapsed_s=elapsed,
        )

    print(f"\nTotal unique triples after Pass 2: {len(all_triples)}")

    # ── Pass 2b: cross-section relationship extraction ────────────────────
    # Groups consecutive chunks into sections and re-runs relationship extraction
    # on each section text. Catches relationships between entities that don't
    # co-occur within the same small chunk.
    section_size = llm_cfg.section_size
    if section_size > 1 and total_chunks > 1:
        sections = [chunks[i:i + section_size] for i in range(0, total_chunks, section_size)]
        # Only run sections that span more than one chunk
        sections = [s for s in sections if len(s) > 1]

    if section_size > 1 and total_chunks > 1 and sections:
        print(f"\n{'═' * 50}")
        print(f"  Pass 2b — Cross-section relationships ({len(sections)} section(s), {section_size} chunks each)")
        print(f"{'═' * 50}")
        triples_before_2b = len(all_triples)

        for sec_idx, section_chunks in enumerate(sections):
            sec_num = sec_idx + 1
            # Reconstruct clean section text: strip the overlap prefix from all
            # chunks after the first so boundary text isn't duplicated.
            parts = [section_chunks[0]]
            for chunk in section_chunks[1:]:
                words = chunk.split()
                parts.append(' '.join(words[llm_cfg.overlap:]))
            section_text = ' '.join(parts)

            chunk_range = f"{sec_idx * section_size + 1}–{sec_idx * section_size + len(section_chunks)}"
            print(f"\n{'─' * 50}")
            print(f"  Section {sec_num}/{len(sections)}  (chunks {chunk_range},  {len(section_text.split())} words)")
            print(f"{'─' * 50}")
            t0 = time.monotonic()

            triples = relationship_extractor.extract(
                section_text,
                canonical_names,
                progress_label=f"section {sec_num}/{len(sections)} · relationships",
            )
            elapsed = time.monotonic() - t0
            bench.record_llm_call(run_id, "section_relationship_extraction", elapsed, chunk_number=sec_num)

            new_count = 0
            for t in triples:
                subj = canonical_lookup.get(t.get('subject', '').lower(), t.get('subject', ''))
                obj = canonical_lookup.get(t.get('object', '').lower(), t.get('object', ''))
                t = {**t, 'subject': subj, 'object': obj}
                key = (t['subject'], t.get('predicate', ''), t['object'])
                if key not in all_triples_set:
                    all_triples_set.add(key)
                    all_triples.append(t)
                    new_count += 1

            print(f"  ✓ Relationships: {len(triples)} found, {new_count} new  ({elapsed:.1f}s)")

        added = len(all_triples) - triples_before_2b
        print(f"\nPass 2b added {added} new triple(s). Total unique triples: {len(all_triples)}")

    # Step 1: Generate TTL knowledge graph.
    print(f"\n1. Generating knowledge graph (TTL)...")
    output_path = _PROJECT_ROOT / output_dir
    writer = TurtleWriter(output_dir=str(output_path))
    kg_path, proposals = writer.write_knowledge_graph(
        document_id=document_id,
        triples=all_triples,
        document_metadata=doc_data,
        entities=list(unique_entities.values()),
    )
    print(f"   Knowledge graph saved to: {kg_path}")

    # Report ontology proposals.
    if proposals:
        print(f"\n   *** {len(proposals)} ontology addition(s) proposed for review ***")
        for p in proposals:
            sources = '; '.join(p['sources']) if p['sources'] else '(no source recorded)'
            print(f"       • {p['label']}  ←  {sources}")
        print(f"   Review: data/ontology/ontology_proposed.ttl")
        print(f"   Approve with: python main.py ontology approve")

    # Derive all output filenames from the document stem — single source of truth.
    original_filename = Path(doc_data['filename']).stem
    graph_html_filename = f"{original_filename}_graph.html"
    markup_output_path = _PROJECT_ROOT / "data" / "documents" / f"{original_filename}_markup.html"
    graph_output_path = _PROJECT_ROOT / "data" / "documents" / graph_html_filename

    # Step 2: Generate HTML markup from TTL.
    print(f"\n2. Generating HTML markup from knowledge graph...")
    markup_generator = HTMLMarkupGenerator()
    html_content = markup_generator.generate_markup_from_ttl(
        text=doc_data['text'],
        ttl_file_path=kg_path,
        document_filename=doc_data['filename'],
        graph_html_filename=graph_html_filename,  # explicit — no naming guesswork
    )
    markup_path = markup_generator.save_markup(html_content, str(markup_output_path))
    print(f"   HTML markup saved to: {markup_path}")

    # Step 3 (optional): Generate interactive graph visualisation
    graph_path = None
    if with_graph:
        print(f"\n3. Generating graph visualisation...")
        graph_path = generate_graph_html(kg_path, str(graph_output_path))

    store = MetadataStore()
    store.add_document(document_id, doc_data, kg_path)
    print(f"Metadata updated")

    total_elapsed = time.monotonic() - run_start
    bench.finish_run(
        run_id,
        chunk_count=total_chunks,
        entities_raw=entities_raw,
        entities_resolved=len(unique_entities),
        triples=len(all_triples),
        elapsed_s=total_elapsed,
        proposals=len(proposals),
    )
    bench.close()

    return {
        'document_id': document_id,
        'kg_path': kg_path,
        'markup_path': markup_path,
        'graph_path': graph_path,
        'entity_count': len(unique_entities),
        'triple_count': len(all_triples),
        'proposals': proposals,
    }


def show_benchmark(view: str = "runs", sql: Optional[str] = None):
    """Display benchmark metrics as a table."""
    bench = create_benchmark_store()
    try:
        if sql:
            rel = bench.query(sql)
        elif view == "runs":
            rel = bench.query(BenchmarkStore.SUMMARY_SQL)
        elif view == "chunks":
            rel = bench.query(BenchmarkStore.CHUNK_SQL)
        elif view == "llm":
            rel = bench.query(BenchmarkStore.LLM_SQL)
        else:
            print(f"Unknown view: {view}. Use: runs | chunks | llm")
            return
        print(rel)
    finally:
        bench.close()


def clear_benchmark():
    bench = create_benchmark_store()
    bench.clear()
    bench.close()
    print("Benchmark data cleared.")


# Subdirectories of data/ that should always exist (recreated after archive clear)
_DATA_SUBDIRS = ["documents", "knowledge_graphs", "ontology"]


def archive_data(name: Optional[str] = None, llmnamed: bool = False):
    """
    Copy data/ to data_save_<name|timestamp>, excluding benchmark.duckdb.
    Update absolute paths in metadata.json and schema:url triples in TTL files
    within the archive to reflect the new location.
    Then clear data/ (except benchmark.duckdb) and recreate empty subdirectories.
    """
    import shutil
    from datetime import datetime, timezone

    if llmnamed:
        from src.extraction.providers.factory import create_provider
        cfg = load_config()
        provider = create_provider(cfg.llm)
        # Trigger auto-detection if model is null; sanitise for use as dir name
        model_name = provider.model
        label = model_name.replace("/", "_").replace(":", "_").replace(" ", "_")
    else:
        label = name or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    src = _PROJECT_ROOT / "data"
    dst = _PROJECT_ROOT / f"data_save_{label}"

    if dst.exists():
        print(f"Archive already exists: {dst}")
        sys.exit(1)

    # Files and dirs to exclude from the copy
    EXCLUDE = {"benchmark.duckdb", "benchmark.duckdb.wal"}

    def _ignore(directory, contents):
        return [c for c in contents if c in EXCLUDE]

    print(f"Archiving {src} → {dst} ...")
    shutil.copytree(src, dst, ignore=_ignore)
    print(f"  Copied (excluding benchmark.duckdb)")

    # ── Update metadata.json ────────────────────────────────────────────────
    meta_file = dst / "metadata.json"
    if meta_file.exists():
        import json
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        old_data_str = str(src.resolve())
        new_data_str = str(dst.resolve())
        updated = 0
        for doc in data.get("documents", {}).values():
            for field in ("path", "kg_path"):
                if field in doc and doc[field] and old_data_str in doc[field]:
                    doc[field] = doc[field].replace(old_data_str, new_data_str)
                    updated += 1
        meta_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Updated {updated} path(s) in metadata.json")

    # ── Update schema:url in TTL files ─────────────────────────────────────
    from rdflib import Graph as RDFGraph
    from rdflib.namespace import XSD
    from rdflib import Literal as RDFLiteral
    SCHEMA_URL = "http://schema.org/url"
    old_data_str = str(src.resolve())
    new_data_str = str(dst.resolve())
    ttl_updated = 0

    for ttl_file in (dst / "knowledge_graphs").glob("*.ttl"):
        g = RDFGraph()
        g.parse(str(ttl_file), format="turtle")
        changes = []
        for s, p, o in g:
            if str(p) == SCHEMA_URL and isinstance(o, RDFLiteral) and old_data_str in str(o):
                changes.append((s, p, o))
        for s, p, o in changes:
            g.remove((s, p, o))
            new_val = str(o).replace(old_data_str, new_data_str)
            g.add((s, p, RDFLiteral(new_val, datatype=XSD.string)))
        if changes:
            g.serialize(destination=str(ttl_file), format="turtle")
            ttl_updated += 1

    print(f"  Updated schema:url in {ttl_updated} TTL file(s)")

    # ── Clear data/ and recreate empty subdirectory structure ───────────────
    KEEP = {"benchmark.duckdb", "benchmark.duckdb.wal"}
    for item in src.iterdir():
        if item.name in KEEP:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for subdir in _DATA_SUBDIRS:
        (src / subdir).mkdir(exist_ok=True)
    # Restore the base ontology (not the run-specific proposed file)
    ontology_src = dst / "ontology" / "ontology.ttl"
    if ontology_src.exists():
        shutil.copy2(ontology_src, src / "ontology" / "ontology.ttl")
    print(f"  Cleared data/ and recreated empty subdirectories")
    print(f"  Restored ontology.ttl to data/ontology/")

    print(f"\nArchive complete: {dst}")
    print("The benchmark database remains at: data/benchmark.duckdb")


def show_ontology_status(ontology_dir: str = "data/ontology"):
    """Show pending ontology proposals and their review status."""
    from src.ontology.proposal_store import ProposalStore
    proposal_file = _PROJECT_ROOT / ontology_dir / "ontology_proposed.ttl"
    ontology_file = _PROJECT_ROOT / ontology_dir / "ontology.ttl"
    if not proposal_file.exists():
        print("No pending ontology proposals.")
        return
    store = ProposalStore(str(proposal_file), str(ontology_file))
    summary = store.status_summary()
    print(f"\nOntology proposals:")
    print(f"  New classes pending:    {summary.get('pending', 0)}")
    print(f"  Entities needing type:  {summary.get('needs_typing', 0)}")
    print(f"  Approved: {summary.get('approved', 0)}   Rejected: {summary.get('rejected', 0)}")
    pending = store.get_pending()
    if pending:
        print(f"\nPending new classes:")
        for cls in pending:
            src = cls.get('proposed_by', '')
            print(f"  • {cls['label']}" + (f"  ← {src}" if src else ""))
    needs_typing = store.get_needs_typing()
    if needs_typing:
        print(f"\nEntities typed as ont:Other (need re-typing):")
        for e in needs_typing[:10]:
            print(f"  • {e['label']}  ← {e['source_ttl'].split('/')[-1]}")
        if len(needs_typing) > 10:
            print(f"  ... and {len(needs_typing) - 10} more")
    if pending or needs_typing:
        print(f"\nRun: python main.py ontology review")


def run_ontology_review(ontology_dir: str = "data/ontology"):
    """Interactively review ontology proposals with LLM + Wikidata."""
    from src.ontology.interactive_review import run_interactive_review
    app_config = load_config()
    proposal_file = str(_PROJECT_ROOT / ontology_dir / "ontology_proposed.ttl")
    ontology_file = str(_PROJECT_ROOT / ontology_dir / "ontology.ttl")

    # Build LLM client for placement proposals
    try:
        from src.extraction.llm_client import LLMClient
        llm_client = LLMClient.from_config()
    except Exception:
        llm_client = None
        print("Warning: LLM not available — placement proposals will be limited.")

    run_interactive_review(
        proposal_file=proposal_file,
        ontology_file=ontology_file,
        llm_client=llm_client,
        wikidata_mode=app_config.ontology.wikidata_mcp,
    )


def approve_ontology(ontology_dir: str = "data/ontology"):
    """Replace ontology.ttl with the reviewed ontology_proposed.ttl."""
    from src.storage.ontology_manager import OntologyManager
    path = _PROJECT_ROOT / ontology_dir
    manager = OntologyManager(str(path))
    n = manager.approve_proposed_ontology()
    if n == 0:
        print("No proposed ontology file found. Nothing to approve.")
    else:
        print(f"Approved {n} new class(es). ontology.ttl updated.")


def run_normalize(subcommand: str, kg_dir: str, ontology_file: str,
                  map_file: str, dry_run: bool, no_llm: bool):
    """Predicate normalization: scan predicates, review map, apply rewrites."""
    from src.normalization.predicate_normalizer import build_predicate_map, apply_predicate_map
    import yaml

    map_path = Path(map_file)

    if subcommand == "scan":
        print(f"Scanning {kg_dir} for predicates...")
        llm_client = None
        if not no_llm:
            try:
                from src.extraction.llm_client import LLMClient
                llm_client = LLMClient.from_config()
                print("  LLM available — will suggest canonical mappings")
            except Exception:
                print("  LLM unavailable — using string similarity only")
        mapping = build_predicate_map(kg_dir, llm_client=llm_client)
        n_groups = len(mapping["mappings"])
        n_review = sum(1 for m in mapping["mappings"] if len(m["variants"]) > 1)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(yaml.dump(mapping, allow_unicode=True, sort_keys=False))
        print(f"\n  {n_groups} predicate groups found, {n_review} with variants to review")
        print(f"  Written to: {map_path}")
        print(f"\nNext: review {map_path}, set 'reviewed: true', then run normalize apply")

    elif subcommand == "apply":
        if not map_path.exists():
            print(f"No predicate map at {map_path}. Run 'normalize scan' first.")
            return
        mapping = yaml.safe_load(map_path.read_text())
        reviewed = [m for m in mapping.get("mappings", []) if m.get("reviewed")]
        if not reviewed:
            print("No mappings marked 'reviewed: true'. Edit the map file first.")
            return
        if dry_run:
            print("Dry run — showing changes without writing files:")
        files, triples = apply_predicate_map(
            kg_dir=kg_dir,
            ontology_file=ontology_file,
            predicate_map={"mappings": reviewed},
            dry_run=dry_run,
        )
        print(f"  {'Would rewrite' if dry_run else 'Rewrote'} {triples} triple(s) in {files} file(s)")
        if not dry_run:
            print(f"  owl:subPropertyOf declarations added to {ontology_file}")
    else:
        print("Usage: python main.py normalize scan|apply [--dry-run] [--no-llm]")


def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description='Knowledge Graph System'
    )
    subparsers = parser.add_subparsers(dest='command')

    # process
    p = subparsers.add_parser('process', help='Process a document')
    p.add_argument('file_path')
    p.add_argument('--output-dir', default='data/knowledge_graphs')
    p.add_argument('--max-chunks', type=int, default=None, help='Limit number of chunks processed (for testing)')
    p.add_argument('--with-graph', action='store_true', help='Also generate interactive graph HTML via ai-knowledge-graph/ttl_to_html.py')

    # server
    s = subparsers.add_parser('server', help='Start n8n API server')
    s.add_argument('--host', default='0.0.0.0')
    s.add_argument('--port', type=int, default=5000)
    s.add_argument('--debug', action='store_true')

    # archive
    arc_p = subparsers.add_parser('archive', help='Archive data/ to data_save_<name> and reset data/')
    arc_p.add_argument('--name', default=None, help='Archive name suffix (default: timestamp)')
    arc_p.add_argument('--llmnamed', action='store_true', help='Name the archive after the current LLM model')

    # ontology
    ont_p = subparsers.add_parser('ontology', help='Ontology management')
    ont_sub = ont_p.add_subparsers(dest='ont_command')
    ont_sub.add_parser('approve', help='Bulk-approve all pending ontology proposals')
    ont_sub.add_parser('review', help='Interactively review ontology proposals with LLM + Wikidata')
    ont_sub.add_parser('status', help='Show pending ontology proposals')

    # normalize
    norm_p = subparsers.add_parser('normalize', help='Predicate normalization: cluster ad-hoc predicates and rewrite TTL files')
    norm_sub = norm_p.add_subparsers(dest='norm_command')
    norm_scan = norm_sub.add_parser('scan', help='Scan TTL files and write predicate_map.yaml')
    norm_scan.add_argument('--no-llm', action='store_true', help='Skip LLM suggestions, use string similarity only')
    norm_apply = norm_sub.add_parser('apply', help='Apply reviewed predicate_map.yaml to TTL files')
    norm_apply.add_argument('--dry-run', action='store_true', help='Show changes without writing files')
    for p_ in (norm_scan, norm_apply):
        p_.add_argument('--kg-dir', default='data/knowledge_graphs')
        p_.add_argument('--ontology-file', default='data/ontology/ontology.ttl')
        p_.add_argument('--map-file', default='data/predicate_map.yaml')

    # benchmark
    bm_p = subparsers.add_parser('benchmark', help='View pipeline benchmark metrics')
    bm_sub = bm_p.add_subparsers(dest='bm_command')
    bm_show = bm_sub.add_parser('show', help='Show benchmark table')
    bm_show.add_argument('view', nargs='?', default='runs', choices=['runs', 'chunks', 'llm'],
                         help='Table to display (default: runs)')
    bm_query = bm_sub.add_parser('query', help='Run a custom SQL query')
    bm_query.add_argument('sql', help='SQL query to execute against the benchmark DB')
    bm_sub.add_parser('clear', help='Delete all benchmark data')

    args = parser.parse_args()

    if args.command == 'process':
        if not run_precheck():
            sys.exit(1)
        result = process_and_extract(args.file_path, args.output_dir, max_chunks=args.max_chunks, with_graph=args.with_graph)
        print("\n" + "=" * 50)
        print("Processing complete!")
        print("=" * 50)
        print(f"Document ID:    {result['document_id']}")
        print(f"Knowledge Graph:{result['kg_path']}")
        print(f"HTML Markup:    {result['markup_path']}")
        print(f"Entities:       {result['entity_count']}")
        print(f"Triples:        {result['triple_count']}")
        if result['proposals']:
            print(f"Ontology proposals: {len(result['proposals'])} (see data/ontology/ontology_proposed.ttl)")

    elif args.command == 'server':
        from src.n8n.server import app
        app.run(host=args.host, port=args.port, debug=args.debug)

    elif args.command == 'archive':
        archive_data(name=args.name, llmnamed=args.llmnamed)

    elif args.command == 'ontology':
        if args.ont_command == 'approve':
            approve_ontology()
        elif args.ont_command == 'status':
            show_ontology_status()
        elif args.ont_command == 'review':
            run_ontology_review()
        else:
            ont_p.print_help()

    elif args.command == 'normalize':
        if args.norm_command in ('scan', 'apply'):
            run_normalize(
                subcommand=args.norm_command,
                kg_dir=str(_PROJECT_ROOT / args.kg_dir),
                ontology_file=str(_PROJECT_ROOT / args.ontology_file),
                map_file=str(_PROJECT_ROOT / args.map_file),
                dry_run=getattr(args, 'dry_run', False),
                no_llm=getattr(args, 'no_llm', False),
            )
        else:
            norm_p.print_help()

    elif args.command == 'benchmark':
        if args.bm_command == 'show':
            show_benchmark(view=args.view)
        elif args.bm_command == 'query':
            show_benchmark(sql=args.sql)
        elif args.bm_command == 'clear':
            clear_benchmark()
        else:
            bm_p.print_help()

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
