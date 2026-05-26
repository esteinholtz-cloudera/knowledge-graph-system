"""Test Turtle file generation without requiring LLM."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.storage.turtle_writer import TurtleWriter


def test_turtle_generation():
    """Test Turtle file generation with sample triples."""
    print("Testing Turtle File Generation")
    print("=" * 50)
    
    # Sample triples (simulating extracted relationships)
    triples = [
        {'subject': 'Cloudera Machine Learning', 'predicate': 'is', 'object': 'platform'},
        {'subject': 'CML', 'predicate': 'provides', 'object': 'data scientists'},
        {'subject': 'CML', 'predicate': 'runsOn', 'object': 'Kubernetes'},
        {'subject': 'CML', 'predicate': 'integratesWith', 'object': 'Apache Spark'},
        {'subject': 'data scientists', 'predicate': 'use', 'object': 'CML'},
        {'subject': 'CML', 'predicate': 'supports', 'object': 'Python'},
        {'subject': 'CML', 'predicate': 'supports', 'object': 'R'},
    ]
    
    # Document metadata
    document_metadata = {
        'filename': 'test_document.txt',
        'path': '/test/test_document.txt',
        'hash': 'test_hash_12345'
    }
    
    document_id = "test_document_001"
    
    print(f"\nSample triples: {len(triples)}")
    for triple in triples[:3]:
        print(f"  - {triple['subject']} --[{triple['predicate']}]--> {triple['object']}")
    
    # Generate Turtle file
    print("\nGenerating Turtle file...")
    writer = TurtleWriter(output_dir="data/knowledge_graphs")
    
    kg_path, _ = writer.write_knowledge_graph(
        document_id=document_id,
        triples=triples,
        document_metadata=document_metadata
    )
    
    print(f"\n✓ Turtle file generated successfully!")
    print(f"  Saved to: {kg_path}")
    
    # Verify file exists
    if Path(kg_path).exists():
        file_size = Path(kg_path).stat().st_size
        print(f"  File size: {file_size} bytes")
        
        # Show first few lines of the file
        print("\nFirst 20 lines of Turtle file:")
        print("-" * 50)
        with open(kg_path, 'r') as f:
            lines = f.readlines()
            for i, line in enumerate(lines[:20], 1):
                print(f"{i:2}: {line.rstrip()}")
        print("-" * 50)
    else:
        print(f"  ERROR: File not found at {kg_path}")
    
    print("\n" + "=" * 50)
    print("Test complete!")
    return kg_path


if __name__ == '__main__':
    try:
        test_turtle_generation()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

