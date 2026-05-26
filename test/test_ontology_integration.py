"""Test ontology integration with TTL generation."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.storage.turtle_writer import TurtleWriter
from src.storage.ontology_manager import OntologyManager
from src.document.html_markup import HTMLMarkupGenerator


def test_ontology_integration():
    """Test ontology integration with TTL generation."""
    print("Testing Ontology Integration")
    print("=" * 50)
    
    # Sample text
    sample_text = """
    Cloudera Machine Learning (CML) is a cloud-native machine learning platform.
    CML provides data scientists with tools for building and deploying ML models.
    The platform runs on Kubernetes and integrates with Apache Spark.
    Data scientists use CML to train models using Python and R.
    
    The company was founded in 2008 and is headquartered in Palo Alto, California.
    """
    
    # Sample entities with types
    entities = [
        {'entity': 'Cloudera Machine Learning', 'type': 'Product'},
        {'entity': 'CML', 'type': 'Technology'},
        {'entity': 'data scientists', 'type': 'Person'},
        {'entity': 'Kubernetes', 'type': 'Technology'},
        {'entity': 'Apache Spark', 'type': 'Technology'},
        {'entity': 'Python', 'type': 'Technology'},
        {'entity': 'R', 'type': 'Technology'},
        {'entity': 'Palo Alto', 'type': 'Location'},
        {'entity': 'California', 'type': 'Location'},
    ]
    
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
        'filename': 'test_ontology_document.txt',
        'path': '/test/test_ontology_document.txt',
        'hash': 'test_ontology_hash_12345'
    }
    
    document_id = "test_ontology_001"
    
    # Step 1: Check ontology manager
    print("\n1. Testing Ontology Manager...")
    ontology_manager = OntologyManager()
    ontology_path = ontology_manager.get_ontology_file_path()
    print(f"   Ontology file: {ontology_path}")
    print(f"   Ontology exists: {Path(ontology_path).exists()}")
    
    # Step 2: Generate TTL with ontology
    print("\n2. Generating TTL file with ontology typing...")
    writer = TurtleWriter(output_dir="data/knowledge_graphs")
    kg_path, _ = writer.write_knowledge_graph(
        document_id=document_id,
        triples=triples,
        document_metadata=document_metadata,
        entities=entities
    )
    print(f"   TTL file saved to: {kg_path}")
    
    # Step 3: Verify rdf:type in TTL
    print("\n3. Verifying rdf:type statements in TTL...")
    from rdflib import Graph
    from rdflib.namespace import RDF
    from src.storage.rdf_utils import ONT
    
    graph = Graph()
    graph.parse(kg_path, format='turtle')
    
    type_count = 0
    for subject, predicate, obj in graph:
        if predicate == RDF.type and str(obj).startswith(str(ONT)):
            type_count += 1
            entity_name = str(subject).split('/')[-1].replace('_', ' ')
            type_name = str(obj).replace(str(ONT), '').replace('_', ' ')
            print(f"     {entity_name} -> rdf:type -> {type_name}")
    
    print(f"   Found {type_count} rdf:type statements")
    
    # Step 4: Generate HTML from TTL
    print("\n4. Generating HTML markup from TTL with ontology types...")
    markup_generator = HTMLMarkupGenerator()
    
    html_content = markup_generator.generate_markup_from_ttl(
        text=sample_text,
        ttl_file_path=kg_path,
        document_filename='test_ontology_document.txt'
    )
    
    markup_path = markup_generator.save_markup(
        html_content,
        'data/documents/test_ontology_markup.html'
    )
    print(f"   HTML markup saved to: {markup_path}")
    
    # Step 5: Verify entity types in HTML
    print("\n5. Verifying entity types extracted from TTL...")
    extracted_entities = markup_generator._extract_entities_from_ttl(kg_path)
    print(f"   Extracted {len(extracted_entities)} entities:")
    for entity in extracted_entities[:5]:
        print(f"     - {entity['entity']} ({entity['type']})")
    
    print("\n" + "=" * 50)
    print("Test complete! Check the TTL file for rdf:type statements.")
    return kg_path, markup_path, ontology_path


if __name__ == '__main__':
    try:
        test_ontology_integration()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

