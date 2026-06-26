"""n8n node for extracting entities."""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.extraction.entity_extractor import EntityExtractor
from src.extraction.relationship_extractor import RelationshipExtractor


def extract_entities(text: str) -> dict:
    """
    Extract entities from text.
    
    Args:
        text: Text to extract entities from
        
    Returns:
        Dictionary with extracted entities
    """
    extractor = EntityExtractor()
    entities = extractor.extract(text).items
    
    return {
        'entities': entities,
        'entity_count': len(entities)
    }


def extract_relationships(text: str, entities: list = None) -> dict:
    """
    Extract relationships from text.
    
    Args:
        text: Text to extract relationships from
        entities: Optional list of entity names to focus on
        
    Returns:
        Dictionary with extracted triples
    """
    extractor = RelationshipExtractor()
    
    # Extract entity names if list of dicts provided
    entity_names = None
    if entities and len(entities) > 0:
        if isinstance(entities[0], dict):
            entity_names = [e.get('entity', '') for e in entities if e.get('entity')]
        else:
            entity_names = entities
    
    triples = extractor.extract(text, entity_names).items
    
    return {
        'triples': triples,
        'triple_count': len(triples)
    }

