"""n8n node for storing knowledge graphs."""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.storage.turtle_writer import TurtleWriter
from src.storage.metadata_store import MetadataStore


def store_knowledge_graph(
    document_id: str,
    triples: list,
    document_metadata: dict = None,
    output_dir: str = "data/knowledge_graphs"
) -> dict:
    """
    Store knowledge graph to Turtle file.
    
    Args:
        document_id: Unique document identifier
        triples: List of triple dictionaries
        document_metadata: Optional document metadata
        output_dir: Output directory for Turtle files
        
    Returns:
        Dictionary with storage information
    """
    writer = TurtleWriter(output_dir=output_dir)
    
    # Write knowledge graph
    kg_path = writer.write_knowledge_graph(
        document_id=document_id,
        triples=triples,
        document_metadata=document_metadata
    )
    
    # Update metadata store
    store = MetadataStore()
    if document_metadata:
        store.add_document(document_id, document_metadata, kg_path)
    else:
        store.update_kg_path(document_id, kg_path)
    
    return {
        'document_id': document_id,
        'kg_path': kg_path,
        'triple_count': len(triples),
        'status': 'success'
    }

