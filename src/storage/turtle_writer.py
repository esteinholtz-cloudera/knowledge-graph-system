"""Write knowledge graphs to Turtle format."""
import os
from pathlib import Path
from rdflib import Graph
from rdflib.namespace import RDF
from typing import List, Dict, Optional
from .rdf_utils import (
    KG, DOC, SCHEMA, ONT,
    create_entity_uri,
    create_predicate_uri,
    create_document_uri,
    sanitize_literal
)
from .ontology_manager import OntologyManager


class TurtleWriter:
    """Write knowledge graphs to Turtle format."""
    
    def __init__(self, output_dir: str = "data/knowledge_graphs", ontology_dir: str = "data/ontology"):
        """
        Initialize Turtle writer.
        
        Args:
            output_dir: Directory to store Turtle files
            ontology_dir: Directory containing ontology files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ontology_manager = OntologyManager(ontology_dir)
    
    def write_knowledge_graph(
        self,
        document_id: str,
        triples: List[Dict],
        document_metadata: Optional[Dict] = None,
        entities: Optional[List[Dict]] = None
    ) -> str:
        """
        Write knowledge graph to Turtle file with ontology typing.
        
        Args:
            document_id: Unique identifier for the document
            triples: List of triple dictionaries with 'subject', 'predicate', 'object'
            document_metadata: Optional metadata about the document
            entities: Optional list of entities with type information
            
        Returns:
            Path to the created Turtle file
        """
        # Create RDF graph
        graph = Graph()
        
        # Bind namespaces
        graph.bind("kg", KG)
        graph.bind("doc", DOC)
        graph.bind("schema", SCHEMA)
        graph.bind("rdfs", "http://www.w3.org/2000/01/rdf-schema#")
        graph.bind("rdf", RDF)
        graph.bind("ont", ONT)  # Add ontology namespace
        
        # Import ontology
        ontology_path = self.ontology_manager.get_ontology_file_path()
        graph.parse(ontology_path, format='turtle')
        
        # Create document URI
        doc_uri = create_document_uri(document_id)
        
        # Add document metadata if provided
        if document_metadata:
            if 'path' in document_metadata:
                graph.add((doc_uri, SCHEMA.url, sanitize_literal(document_metadata['path'])))
            if 'filename' in document_metadata:
                graph.add((doc_uri, SCHEMA.name, sanitize_literal(document_metadata['filename'])))
            if 'hash' in document_metadata:
                graph.add((doc_uri, KG.hash, sanitize_literal(document_metadata['hash'])))
        
        # Track entities and their types
        entity_types = {}
        if entities:
            for entity in entities:
                entity_name = entity.get('entity', '').strip()
                entity_type = entity.get('type', 'Other').strip()
                if entity_name:
                    entity_types[entity_name] = entity_type
                    # Ensure ontology class exists
                    self.ontology_manager.ensure_class_exists(entity_type)
        
        # Add triples to graph
        for triple in triples:
            subject = triple.get('subject', '').strip()
            predicate = triple.get('predicate', '').strip()
            obj = triple.get('object', '').strip()
            
            if not subject or not predicate or not obj:
                continue
            
            # Create URIs
            subj_uri = create_entity_uri(subject)
            pred_uri = create_predicate_uri(predicate)
            obj_uri = create_entity_uri(obj)
            
            # Add triple
            graph.add((subj_uri, pred_uri, obj_uri))
            
            # Link entities to document
            graph.add((subj_uri, DOC.sourceDocument, doc_uri))
            graph.add((obj_uri, DOC.sourceDocument, doc_uri))
            
            # Add rdf:type for subject if type is known
            if subject in entity_types:
                type_class = self.ontology_manager.get_ontology_class_uri(entity_types[subject])
                graph.add((subj_uri, RDF.type, type_class))
            
            # Add rdf:type for object if type is known
            if obj in entity_types:
                type_class = self.ontology_manager.get_ontology_class_uri(entity_types[obj])
                graph.add((obj_uri, RDF.type, type_class))
        
        # Generate filename
        filename = f"{document_id}.ttl"
        filepath = self.output_dir / filename
        
        # Write to file
        graph.serialize(destination=str(filepath), format='turtle')
        
        return str(filepath)
    
    def get_knowledge_graph_path(self, document_id: str) -> Optional[str]:
        """
        Get the path to a knowledge graph file for a document.
        
        Args:
            document_id: Document identifier
            
        Returns:
            Path to Turtle file if it exists, None otherwise
        """
        filename = f"{document_id}.ttl"
        filepath = self.output_dir / filename
        
        if filepath.exists():
            return str(filepath)
        return None

