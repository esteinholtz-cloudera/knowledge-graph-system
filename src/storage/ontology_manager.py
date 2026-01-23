"""Ontology manager for loading and managing local ontology."""
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL
from typing import Dict, Optional
from urllib.parse import quote


# Local ontology namespace
ONT = Namespace("http://example.org/ontology/")


class OntologyManager:
    """Manage local ontology and entity type mappings."""
    
    def __init__(self, ontology_dir: str = "data/ontology"):
        """
        Initialize ontology manager.
        
        Args:
            ontology_dir: Directory containing ontology files
        """
        self.ontology_dir = Path(ontology_dir)
        self.ontology_dir.mkdir(parents=True, exist_ok=True)
        self.ontology_file = self.ontology_dir / "ontology.ttl"
        self.graph = Graph()
        self._load_ontology()
    
    def _load_ontology(self):
        """Load ontology from file or create default."""
        if self.ontology_file.exists():
            self.graph.parse(str(self.ontology_file), format='turtle')
        else:
            self._create_default_ontology()
            self._save_ontology()
    
    def _create_default_ontology(self):
        """Create default ontology with common entity types."""
        from rdflib.namespace import XSD
        
        # Bind namespaces
        self.graph.bind("ont", ONT)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        self.graph.bind("owl", OWL)
        self.graph.bind("xsd", XSD)
        
        # Define default entity type classes
        entity_types = {
            'Person': 'A human being or individual',
            'Organization': 'A company, institution, or group',
            'Location': 'A geographical place or location',
            'Technology': 'A technology, tool, or platform',
            'Concept': 'An abstract concept or idea',
            'Product': 'A product or service',
            'Event': 'An event or occurrence',
            'Date': 'A date or time period',
            'Other': 'Other type of entity'
        }
        
        # Create classes in ontology
        for type_name, description in entity_types.items():
            class_uri = ONT[type_name]
            self.graph.add((class_uri, RDF.type, OWL.Class))
            self.graph.add((class_uri, RDFS.label, Literal(type_name)))
            self.graph.add((class_uri, RDFS.comment, Literal(description)))
    
    def _save_ontology(self):
        """Save ontology to file."""
        self.graph.serialize(destination=str(self.ontology_file), format='turtle')
    
    def get_ontology_class_uri(self, entity_type: str) -> URIRef:
        """
        Get ontology class URI for an entity type.
        
        Args:
            entity_type: Entity type name (e.g., "Person", "Organization")
            
        Returns:
            URI of the ontology class
        """
        # Sanitize type name
        sanitized = quote(entity_type.strip().replace(' ', '_'), safe='')
        return ONT[sanitized]
    
    def ensure_class_exists(self, entity_type: str, description: Optional[str] = None):
        """
        Ensure an ontology class exists, create if it doesn't.
        
        Args:
            entity_type: Entity type name
            description: Optional description for the class
        """
        class_uri = self.get_ontology_class_uri(entity_type)
        
        # Check if class already exists
        if (class_uri, RDF.type, OWL.Class) not in self.graph:
            self.graph.add((class_uri, RDF.type, OWL.Class))
            self.graph.add((class_uri, RDFS.label, Literal(entity_type)))
            if description:
                self.graph.add((class_uri, RDFS.comment, Literal(description)))
            self._save_ontology()
    
    def get_ontology_file_path(self) -> str:
        """Get path to ontology file."""
        return str(self.ontology_file)
    
    def get_ontology_graph(self) -> Graph:
        """Get the ontology graph."""
        return self.graph

