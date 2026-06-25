"""RDF utilities for knowledge graph operations."""
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD
from urllib.parse import quote
import hashlib


# Define namespaces
KG = Namespace("http://example.org/kg/")
DOC = Namespace("http://example.org/doc/")
SCHEMA = Namespace("http://schema.org/")
ONT = Namespace("http://example.org/ontology/")  # Local ontology namespace


def normalise_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip the ends."""
    return " ".join(text.split())


def canonical_match_key(entity_name: str) -> str:
    """Case- and spacing-insensitive grouping key for entity surface variants.

    "HDFS", "Hdfs", "hdfs" and "7.1.9  SP1" / "7.1.9 SP1" all map to one key,
    so case- and spacing-drift duplicates collapse to a single canonical entity.
    Casing/spacing errors are corrected here (postprocessing) rather than via
    prompt tuning.
    """
    return normalise_whitespace(entity_name).casefold()


def normalise_entity_name(entity_name: str) -> str:
    """
    Normalise an entity name for consistent URI generation.

    Only whitespace is normalised (collapsed to single spaces) so spacing
    drift ("7.1.9  SP1" vs "7.1.9 SP1") resolves to the same URI. Original
    casing is preserved so acronyms stay verbatim (HDFS stays HDFS, not Hdfs).
    A single canonical surface form per entity is chosen upstream during
    deduplication/resolution, so case variants never reach this point.
    """
    return normalise_whitespace(entity_name)


def create_entity_uri(entity_name: str, namespace: Namespace = KG) -> URIRef:
    """
    Create a URI for an entity.

    The name's whitespace is normalised before URI generation; casing is
    preserved so the canonical acronym form (e.g. HDFS) is kept verbatim.
    """
    normalised = normalise_entity_name(entity_name)
    sanitized = quote(normalised.replace(' ', '_'), safe='')
    return namespace[sanitized]


def create_predicate_uri(predicate: str, namespace: Namespace = KG) -> URIRef:
    """
    Create a URI for a predicate/relationship.
    
    Args:
        predicate: Name of the predicate
        namespace: RDF namespace to use
        
    Returns:
        URIRef for the predicate
    """
    # Sanitize predicate name
    sanitized = quote(predicate.strip().replace(' ', '_'), safe='')
    return namespace[sanitized]


def create_document_uri(document_id: str, namespace: Namespace = DOC) -> URIRef:
    """
    Create a URI for a document.
    
    Args:
        document_id: Unique identifier for the document
        namespace: RDF namespace to use
        
    Returns:
        URIRef for the document
    """
    sanitized = quote(document_id, safe='')
    return namespace[sanitized]


def sanitize_literal(value: str) -> Literal:
    """
    Create a sanitized literal from a string value.
    
    Args:
        value: String value
        
    Returns:
        Literal object
    """
    # Clean up the value
    cleaned = value.strip()
    return Literal(cleaned, datatype=XSD.string)

