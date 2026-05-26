"""Test HTML generation from TTL file."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.document.html_markup import HTMLMarkupGenerator
from src.storage.turtle_writer import TurtleWriter


def test_ttl_to_html():
    """Test generating HTML markup from TTL file."""
    print("Testing HTML Generation from TTL File")
    print("=" * 50)
    
    # Sample text
    sample_text = """
    Cloudera Machine Learning (CML) is a cloud-native machine learning platform.
    CML provides data scientists with tools for building and deploying ML models.
    The platform runs on Kubernetes and integrates with Apache Spark.
    Data scientists use CML to train models using Python and R.
    
    The company was founded in 2008 and is headquartered in Palo Alto, California.
    """
    
    # Sample triples
    triples = [
        {'subject': 'Cloudera Machine Learning', 'predicate': 'is', 'object': 'platform'},
        {'subject': 'CML', 'predicate': 'provides', 'object': 'data scientists'},
        {'subject': 'CML', 'predicate': 'runsOn', 'object': 'Kubernetes'},
        {'subject': 'CML', 'predicate': 'integratesWith', 'object': 'Apache Spark'},
        {'subject': 'data scientists', 'predicate': 'use', 'object': 'CML'},
        {'subject': 'CML', 'predicate': 'supports', 'object': 'Python'},
        {'subject': 'CML', 'predicate': 'supports', 'object': 'R'},
    ]
    
    document_metadata = {
        'filename': 'test_document.txt',
        'path': '/test/test_document.txt',
        'hash': 'test_hash_12345'
    }
    
    document_id = "test_ttl_to_html_001"
    
    # Step 1: Generate TTL file
    print("\n1. Generating TTL file...")
    writer = TurtleWriter(output_dir="data/knowledge_graphs")
    kg_path, _ = writer.write_knowledge_graph(
        document_id=document_id,
        triples=triples,
        document_metadata=document_metadata
    )
    print(f"   TTL file saved to: {kg_path}")
    
    # Step 2: Generate HTML from TTL
    print("\n2. Generating HTML markup from TTL file...")
    markup_generator = HTMLMarkupGenerator()
    
    html_content = markup_generator.generate_markup_from_ttl(
        text=sample_text,
        ttl_file_path=kg_path,
        document_filename='test_document.txt'
    )
    
    # Save HTML
    markup_path = markup_generator.save_markup(
        html_content,
        'data/documents/test_ttl_to_html_markup.html'
    )
    
    print(f"   HTML markup saved to: {markup_path}")
    print(f"   File size: {Path(markup_path).stat().st_size} bytes")
    
    # Verify entities were extracted from TTL
    print("\n3. Verifying entity extraction from TTL...")
    entities = markup_generator._extract_entities_from_ttl(kg_path)
    print(f"   Extracted {len(entities)} entities from TTL:")
    for entity in entities[:5]:
        print(f"     - {entity['entity']} (URI: {entity['uri']})")
    
    print("\n" + "=" * 50)
    print("Test complete! Open the HTML file to see entities linked to TTL.")
    return kg_path, markup_path


if __name__ == '__main__':
    try:
        test_ttl_to_html()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

