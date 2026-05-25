"""Main CLI entry point for knowledge graph system."""
import argparse
import sys
import time
from pathlib import Path

from src.config.settings import load_config
from src.document.processor import DocumentProcessor
from src.document.html_markup import HTMLMarkupGenerator
from src.extraction.entity_extractor import EntityExtractor
from src.extraction.entity_resolver import EntityResolver
from src.extraction.relationship_extractor import RelationshipExtractor
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
        if llm.model in available:
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


def process_and_extract(file_path: str, output_dir: str = "data/knowledge_graphs", max_chunks: int = None):
    """Process a document and extract knowledge graph."""
    print(f"Processing document: {file_path}")

    processor = DocumentProcessor()
    doc_data = processor.process_document(file_path)
    document_id = doc_data['hash']

    print(f"Document ID: {document_id}")
    print(f"Word count:  {doc_data['word_count']}")

    chunks = processor.chunk_text(doc_data['text'])
    if max_chunks and len(chunks) > max_chunks:
        print(f"Split into {len(chunks)} chunks (limiting to first {max_chunks})")
        chunks = chunks[:max_chunks]
    else:
        print(f"Split into {len(chunks)} chunks")

    entity_extractor = EntityExtractor()
    relationship_extractor = RelationshipExtractor()

    all_entities = []
    all_triples_set = set()  # deduplicate as (subject, predicate, object) tuples
    all_triples = []
    total_chunks = len(chunks)
    chunk_times: list = []

    for i, chunk in enumerate(chunks):
        chunk_num = i + 1
        # ETA based on average of completed chunks
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

        entities = entity_extractor.extract(
            chunk,
            progress_label=f"chunk {chunk_num}/{total_chunks} · entities",
        )
        all_entities.extend(entities)
        print(f"  ✓ Entities:      {len(entities)}")

        entity_names = [e.get('entity', '') for e in entities if e.get('entity')]
        triples = relationship_extractor.extract(
            chunk,
            entity_names,
            progress_label=f"chunk {chunk_num}/{total_chunks} · relationships",
        )
        for t in triples:
            key = (t.get('subject', ''), t.get('predicate', ''), t.get('object', ''))
            if key not in all_triples_set:
                all_triples_set.add(key)
                all_triples.append(t)
        elapsed = time.monotonic() - chunk_start
        chunk_times.append(elapsed)
        print(f"  ✓ Relationships: {len(triples)}  ({elapsed:.1f}s)")

    # Deduplicate entities — prefer a non-'Other' type if seen in any chunk.
    unique_entities: dict = {}
    for entity in all_entities:
        name = entity.get('entity', '')
        if not name:
            continue
        existing = unique_entities.get(name)
        if existing is None or existing.get('type', 'Other') == 'Other':
            unique_entities[name] = entity

    print(f"\nTotal unique entities: {len(unique_entities)}")
    print(f"Total unique triples:  {len(all_triples)}")

    # Entity resolution pass (if enabled in config)
    app_config = load_config()
    if app_config.entity_resolution.enabled:
        print(f"\nRunning entity resolution ({', '.join(app_config.entity_resolution.strategies)})...")
        resolver = EntityResolver(app_config.entity_resolution, llm_client=None)
        resolved_list = resolver.resolve(list(unique_entities.values()))
        unique_entities = {e['entity']: e for e in resolved_list}
        print(f"  After resolution: {len(unique_entities)} entities")

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

    # Step 2: Generate HTML markup from TTL.
    print(f"\n2. Generating HTML markup from knowledge graph...")
    markup_generator = HTMLMarkupGenerator()
    html_content = markup_generator.generate_markup_from_ttl(
        text=doc_data['text'],
        ttl_file_path=kg_path,
        document_filename=doc_data['filename'],
    )
    original_filename = Path(doc_data['filename']).stem
    markup_output_path = _PROJECT_ROOT / "data" / "documents" / f"{original_filename}_markup.html"
    markup_path = markup_generator.save_markup(html_content, str(markup_output_path))
    print(f"   HTML markup saved to: {markup_path}")

    store = MetadataStore()
    store.add_document(document_id, doc_data, kg_path)
    print(f"Metadata updated")

    return {
        'document_id': document_id,
        'kg_path': kg_path,
        'markup_path': markup_path,
        'entity_count': len(unique_entities),
        'triple_count': len(all_triples),
        'proposals': proposals,
    }


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

    # server
    s = subparsers.add_parser('server', help='Start n8n API server')
    s.add_argument('--host', default='0.0.0.0')
    s.add_argument('--port', type=int, default=5000)
    s.add_argument('--debug', action='store_true')

    # ontology
    ont_p = subparsers.add_parser('ontology', help='Ontology management')
    ont_sub = ont_p.add_subparsers(dest='ont_command')
    ont_sub.add_parser('approve', help='Approve proposed ontology additions')

    args = parser.parse_args()

    if args.command == 'process':
        if not run_precheck():
            sys.exit(1)
        result = process_and_extract(args.file_path, args.output_dir, max_chunks=args.max_chunks)
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

    elif args.command == 'ontology':
        if args.ont_command == 'approve':
            approve_ontology()
        else:
            ont_p.print_help()

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
