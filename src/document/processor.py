"""Unified document processing interface."""
import os
import hashlib
from pathlib import Path
from typing import Dict, List, Optional
from .parsers import get_parser


class DocumentProcessor:
    """Process documents of various formats and extract text content."""
    
    def __init__(self, chunk_size: int = 1000, overlap: int = 100):
        """
        Initialize document processor.
        
        Args:
            chunk_size: Number of words per chunk
            overlap: Number of overlapping words between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def process_document(self, file_path: str) -> Dict:
        """
        Process a document and extract text content.
        
        Args:
            file_path: Path to the document file
            
        Returns:
            Dictionary with document metadata and text content
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Document not found: {file_path}")
        
        # Get parser for file type
        parser = get_parser(file_path)
        
        # Extract text
        text = parser.parse(file_path)
        
        # Calculate file hash
        file_hash = self._calculate_file_hash(file_path)
        
        # Get file metadata
        file_stat = os.stat(file_path)
        
        return {
            'path': os.path.abspath(file_path),
            'filename': os.path.basename(file_path),
            'extension': Path(file_path).suffix.lower(),
            'size': file_stat.st_size,
            'hash': file_hash,
            'text': text,
            'word_count': len(text.split())
        }
    
    def chunk_text(self, text: str) -> List[str]:
        """
        Split text into chunks with overlap.
        
        Args:
            text: Text to chunk
            
        Returns:
            List of text chunks
        """
        words = text.split()
        chunks = []
        
        if len(words) <= self.chunk_size:
            return [text]
        
        start = 0
        while start < len(words):
            end = start + self.chunk_size
            chunk_words = words[start:end]
            chunks.append(' '.join(chunk_words))
            
            if end >= len(words):
                break
            
            # Move start forward by chunk_size - overlap
            start = end - self.overlap
        
        return chunks
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

