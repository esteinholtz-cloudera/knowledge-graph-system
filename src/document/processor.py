"""Unified document processing interface."""
import hashlib
import os
from pathlib import Path
from typing import Dict, List

from .chunking import ChunkStrategy, chunk_text
from .parsers import get_parser


class DocumentProcessor:
    """Process documents of various formats and extract text content."""

    def __init__(
        self,
        chunk_size: int = 1000,
        overlap: int = 100,
        chunk_strategy: ChunkStrategy = "recursive",
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.chunk_strategy = chunk_strategy

    def process_document(self, file_path: str) -> Dict:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Document not found: {file_path}")

        parser = get_parser(file_path)
        text = parser.parse(file_path)
        file_stat = os.stat(file_path)

        return {
            "path": os.path.abspath(file_path),
            "filename": os.path.basename(file_path),
            "extension": Path(file_path).suffix.lower(),
            "size": file_stat.st_size,
            "hash": self._calculate_file_hash(file_path),
            "text": text,
            "word_count": len(text.split()),
        }

    def chunk_text(self, text: str) -> List[str]:
        return chunk_text(
            text,
            strategy=self.chunk_strategy,
            chunk_size=self.chunk_size,
            overlap=self.overlap,
        )

    def _calculate_file_hash(self, file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as file_handle:
            for byte_block in iter(lambda: file_handle.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
