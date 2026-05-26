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


def normalise_entity_name(entity_name: str) -> str:
    """
    Normalise an entity name for consistent URI generation.

    ALL_CAPS words are converted to Title Case so that HAMLET and Hamlet
    produce the same URI.  Mixed-case names (e.g. "LLM", "iPhone") are
    left unchanged.
    """
    words = entity_name.strip().split()
    normalised = []
    for word in words:
        # Convert ALL-CAPS words of 4+ chars (proper names like HAMLET, KING).
        # Short ALL-CAPS (LLM, RAG, API, ...) are preserved as-is.
        if word.isalpha() and word.isupper() and len(word) >= 4:
            normalised.append(word.title())
        else:
            normalised.append(word)
    return " ".join(normalised)


def create_entity_uri(entity_name: str, namespace: Namespace = KG) -> URIRef:
    """
    Create a URI for an entity.

    Entity names are normalised (ALL_CAPS → Title Case) before URI generation
    so that HAMLET and Hamlet resolve to the same kg:Hamlet URI.
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

