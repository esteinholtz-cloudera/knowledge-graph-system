"""n8n node for processing documents."""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.document.processor import DocumentProcessor


def process_document(file_path: str, chunk_size: int = 1000, overlap: int = 100) -> dict:
    """
    Process a document and extract text.
    
    Args:
        file_path: Path to the document
        chunk_size: Words per chunk
        overlap: Overlapping words between chunks
        
    Returns:
        Dictionary with document metadata and text chunks
    """
    processor = DocumentProcessor(chunk_size=chunk_size, overlap=overlap)
    
    # Process document
    doc_data = processor.process_document(file_path)
    
    # Chunk text
    chunks = processor.chunk_text(doc_data['text'])
    
    return {
        'document_id': doc_data['hash'],  # Use hash as document ID
        'metadata': doc_data,
        'chunks': chunks,
        'chunk_count': len(chunks)
    }

