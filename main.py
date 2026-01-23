"""Main CLI entry point for knowledge graph system."""
import argparse
import sys
from pathlib import Path

from src.document.processor import DocumentProcessor
from src.document.html_markup import HTMLMarkupGenerator
from src.extraction.entity_extractor import EntityExtractor
from src.extraction.relationship_extractor import RelationshipExtractor
from src.storage.turtle_writer import TurtleWriter
from src.storage.metadata_store import MetadataStore


def process_and_extract(file_path: str, output_dir: str = "data/knowledge_graphs"):
    """Process a document and extract knowledge graph."""
    print(f"Processing document: {file_path}")
    
    # Process document
    processor = DocumentProcessor()
    doc_data = processor.process_document(file_path)
    document_id = doc_data['hash']
    
    print(f"Document ID: {document_id}")
    print(f"Word count: {doc_data['word_count']}")
    
    # Chunk text
    chunks = processor.chunk_text(doc_data['text'])
    print(f"Split into {len(chunks)} chunks")
    
    # Extract entities and relationships
    entity_extractor = EntityExtractor()
    relationship_extractor = RelationshipExtractor()
    
    all_entities = []
    all_triples = []
    
    for i, chunk in enumerate(chunks):
        print(f"\nProcessing chunk {i+1}/{len(chunks)}...")
        
        # Extract entities
        entities = entity_extractor.extract(chunk)
        all_entities.extend(entities)
        print(f"  Extracted {len(entities)} entities")
        
        # Extract relationships
        entity_names = [e.get('entity', '') for e in entities if e.get('entity')]
        triples = relationship_extractor.extract(chunk, entity_names)
        all_triples.extend(triples)
        print(f"  Extracted {len(triples)} relationships")
    
    # Deduplicate entities
    unique_entities = {}
    for entity in all_entities:
        entity_name = entity.get('entity', '')
        if entity_name and entity_name not in unique_entities:
            unique_entities[entity_name] = entity
    
    print(f"\nTotal unique entities: {len(unique_entities)}")
    print(f"Total triples: {len(all_triples)}")
    
    # Step 1: Store knowledge graph (generate TTL file first)
    print(f"\n1. Generating knowledge graph (TTL file)...")
    writer = TurtleWriter(output_dir=output_dir)
    kg_path = writer.write_knowledge_graph(
        document_id=document_id,
        triples=all_triples,
        document_metadata=doc_data,
        entities=list(unique_entities.values())  # Pass entities with types
    )
    
    print(f"   Knowledge graph saved to: {kg_path}")
    
    # Step 2: Generate HTML markup from TTL file
    print(f"\n2. Generating HTML markup from knowledge graph...")
    markup_generator = HTMLMarkupGenerator()
    
    # Generate HTML content from TTL file
    html_content = markup_generator.generate_markup_from_ttl(
        text=doc_data['text'],
        ttl_file_path=kg_path,
        document_filename=doc_data['filename']
    )
    
    # Determine output path for markup file
    original_filename = Path(doc_data['filename']).stem  # filename without extension
    markup_filename = f"{original_filename}_markup.html"
    markup_output_path = Path("data/documents") / markup_filename
    
    # Save markup file
    markup_path = markup_generator.save_markup(html_content, str(markup_output_path))
    print(f"   HTML markup saved to: {markup_path}")
    
    # Update metadata
    store = MetadataStore()
    store.add_document(document_id, doc_data, kg_path)
    
    print(f"Metadata updated")
    
    return {
        'document_id': document_id,
        'kg_path': kg_path,
        'markup_path': markup_path,
        'entity_count': len(unique_entities),
        'triple_count': len(all_triples)
    }


def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description='Knowledge Graph System - Extract and store knowledge graphs from documents'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Process command
    process_parser = subparsers.add_parser('process', help='Process a document and extract knowledge graph')
    process_parser.add_argument('file_path', help='Path to document file')
    process_parser.add_argument('--output-dir', default='data/knowledge_graphs', help='Output directory for Turtle files')
    
    # Server command
    server_parser = subparsers.add_parser('server', help='Start n8n API server')
    server_parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    server_parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    server_parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    if args.command == 'process':
        result = process_and_extract(args.file_path, args.output_dir)
        print("\n" + "="*50)
        print("Processing complete!")
        print("="*50)
        print(f"Document ID: {result['document_id']}")
        print(f"Knowledge Graph: {result['kg_path']}")
        print(f"HTML Markup: {result['markup_path']}")
        print(f"Entities: {result['entity_count']}")
        print(f"Triples: {result['triple_count']}")
    elif args.command == 'server':
        from src.n8n.server import app
        app.run(host=args.host, port=args.port, debug=args.debug)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

