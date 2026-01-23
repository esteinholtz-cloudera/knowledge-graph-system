"""Simple test for HTML markup generation."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.document.html_markup import HTMLMarkupGenerator


def test_html_markup():
    """Test HTML markup generation with sample data."""
    print("Testing HTML Markup Generator")
    print("=" * 50)
    
    # Sample text
    sample_text = """
    Cloudera Machine Learning (CML) is a cloud-native machine learning platform.
    CML provides data scientists with tools for building and deploying ML models.
    The platform runs on Kubernetes and integrates with Apache Spark.
    Data scientists use CML to train models using Python and R.
    
    The company was founded in 2008 and is headquartered in Palo Alto, California.
    """
    
    # Sample entities (simulating what would be extracted)
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
    
    print(f"\nSample text length: {len(sample_text)} characters")
    print(f"Number of entities: {len(entities)}")
    print("\nEntities:")
    for entity in entities:
        print(f"  - {entity['entity']} ({entity['type']})")
    
    # Generate HTML markup
    print("\nGenerating HTML markup...")
    markup_generator = HTMLMarkupGenerator()
    
    html_content = markup_generator.generate_markup(
        text=sample_text,
        entities=entities,
        document_filename='test_document.txt'
    )
    
    # Save markup file
    output_path = Path('data/documents/test_document_markup.html')
    markup_path = markup_generator.save_markup(html_content, str(output_path))
    
    print(f"\n✓ HTML markup generated successfully!")
    print(f"  Saved to: {markup_path}")
    print(f"  File size: {Path(markup_path).stat().st_size} bytes")
    
    # Show a preview of the HTML
    print("\nHTML preview (first 500 characters):")
    print("-" * 50)
    print(html_content[:500] + "...")
    print("-" * 50)
    
    print("\n" + "=" * 50)
    print("Test complete! Open the HTML file in a browser to view the markup.")
    return markup_path


if __name__ == '__main__':
    try:
        test_html_markup()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

