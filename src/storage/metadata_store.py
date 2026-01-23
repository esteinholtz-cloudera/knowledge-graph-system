"""Metadata store for tracking document-KG mappings."""
import json
import os
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime


class MetadataStore:
    """Store metadata about documents and their knowledge graphs."""
    
    def __init__(self, store_path: str = "data/metadata.json"):
        """
        Initialize metadata store.
        
        Args:
            store_path: Path to JSON metadata file
        """
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict:
        """Load metadata from file."""
        if self.store_path.exists():
            try:
                with open(self.store_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save_metadata(self):
        """Save metadata to file."""
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(self._metadata, f, indent=2, ensure_ascii=False)
    
    def add_document(
        self,
        document_id: str,
        document_metadata: Dict,
        kg_path: Optional[str] = None
    ):
        """
        Add or update document metadata.
        
        Args:
            document_id: Unique identifier for the document
            document_metadata: Metadata about the document
            kg_path: Path to the knowledge graph Turtle file
        """
        if 'documents' not in self._metadata:
            self._metadata['documents'] = {}
        
        self._metadata['documents'][document_id] = {
            **document_metadata,
            'kg_path': kg_path,
            'processed_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        self._save_metadata()
    
    def get_document(self, document_id: str) -> Optional[Dict]:
        """
        Get document metadata.
        
        Args:
            document_id: Document identifier
            
        Returns:
            Document metadata dictionary or None
        """
        if 'documents' not in self._metadata:
            return None
        return self._metadata['documents'].get(document_id)
    
    def get_kg_path(self, document_id: str) -> Optional[str]:
        """
        Get knowledge graph path for a document.
        
        Args:
            document_id: Document identifier
            
        Returns:
            Path to Turtle file or None
        """
        doc = self.get_document(document_id)
        if doc:
            return doc.get('kg_path')
        return None
    
    def list_documents(self) -> List[str]:
        """
        List all document IDs.
        
        Returns:
            List of document IDs
        """
        if 'documents' not in self._metadata:
            return []
        return list(self._metadata['documents'].keys())
    
    def update_kg_path(self, document_id: str, kg_path: str):
        """
        Update knowledge graph path for a document.
        
        Args:
            document_id: Document identifier
            kg_path: Path to Turtle file
        """
        if 'documents' not in self._metadata:
            self._metadata['documents'] = {}
        
        if document_id not in self._metadata['documents']:
            self._metadata['documents'][document_id] = {}
        
        self._metadata['documents'][document_id]['kg_path'] = kg_path
        self._metadata['documents'][document_id]['updated_at'] = datetime.now().isoformat()
        
        self._save_metadata()

