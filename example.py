"""Example script demonstrating knowledge graph extraction."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.document.processor import DocumentProcessor
from src.document.html_markup import HTMLMarkupGenerator
from src.extraction.entity_extractor import EntityExtractor
from src.extraction.relationship_extractor import RelationshipExtractor
from src.storage.turtle_writer import TurtleWriter
from src.storage.metadata_store import MetadataStore


def example_extraction():
    """Example of extracting knowledge graph from text."""
    # Example text
    sample_text = """
    Cloudera Machine Learning (CML) is a cloud-native machine learning platform.
    CML provides data scientists with tools for building and deploying ML models.
    The platform runs on Kubernetes and integrates with Apache Spark.
    Data scientists use CML to train models using Python and R.
    """
    
    print("Example: Knowledge Graph Extraction")
    print("=" * 50)
    
    # Extract entities
    print("\n1. Extracting entities...")
    entity_extractor = EntityExtractor()
    entities = entity_extractor.extract(sample_text)
    print(f"   Found {len(entities)} entities:")
    for entity in entities[:5]:  # Show first 5
        print(f"   - {entity.get('entity')} ({entity.get('type')})")
    
    # Extract relationships
    print("\n2. Extracting relationships...")
    relationship_extractor = RelationshipExtractor()
    entity_names = [e.get('entity', '') for e in entities if e.get('entity')]
    triples = relationship_extractor.extract(sample_text, entity_names)
    print(f"   Found {len(triples)} relationships:")
    for triple in triples[:5]:  # Show first 5
        print(f"   - {triple.get('subject')} --[{triple.get('predicate')}]--> {triple.get('object')}")
    
    # Store knowledge graph
    print("\n3. Storing knowledge graph...")
    document_id = "example_001"
    writer = TurtleWriter(output_dir="data/knowledge_graphs")
    kg_path = writer.write_knowledge_graph(
        document_id=document_id,
        triples=triples,
        document_metadata={
            'filename': 'example.txt',
            'path': '/example/example.txt'
        }
    )
    print(f"   Knowledge graph saved to: {kg_path}")
    
    # Update metadata
    print("\n4. Updating metadata...")
    store = MetadataStore()
    store.add_document(
        document_id,
        {'filename': 'example.txt', 'path': '/example/example.txt'},
        kg_path
    )
    print("   Metadata updated")
    
    # Generate HTML markup
    print("\n5. Generating HTML markup...")
    markup_generator = HTMLMarkupGenerator()
    html_content = markup_generator.generate_markup(
        text=sample_text,
        entities=entities,
        document_filename='example.txt'
    )
    markup_path = markup_generator.save_markup(
        html_content,
        'data/documents/example_markup.html'
    )
    print(f"   HTML markup saved to: {markup_path}")
    
    print("\n" + "=" * 50)
    print("Example complete!")


if __name__ == '__main__':
    try:
        example_extraction()
    except Exception as e:
        print(f"\nError: {e}")
        print("\nNote: This example requires the RAG LLM to be set up.")
        print("Make sure the RAG chatbot project is accessible.")
        sys.exit(1)

