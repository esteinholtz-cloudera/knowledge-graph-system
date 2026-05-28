"""Write knowledge graphs to Turtle format."""
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from .ontology_manager import ISA_PREDICATES, OntologyManager
from .rdf_utils import DOC, KG, ONT, SCHEMA, create_document_uri, create_entity_uri, sanitize_literal


def _is_isa_predicate(predicate: str) -> bool:
    """Return True if the predicate expresses an is-a / instance-of relationship."""
    return predicate.strip().lower().replace('-', '_') in ISA_PREDICATES


class TurtleWriter:
    """Write knowledge graphs to Turtle format."""

    def __init__(
        self,
        output_dir: str = "data/knowledge_graphs",
        ontology_dir: str = "data/ontology",
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ontology_manager = OntologyManager(ontology_dir)

    def write_knowledge_graph(
        self,
        document_id: str,
        triples: List[Dict],
        document_metadata: Optional[Dict] = None,
        entities: Optional[List[Dict]] = None,
    ) -> Tuple[str, List[Dict]]:
        """
        Write knowledge graph to Turtle file with ontology typing.

        Returns:
            (kg_path, proposals) where proposals is the list of ontology
            class candidates that need human approval.
        """
        graph = Graph()
        graph.bind("kg", KG)
        graph.bind("doc", DOC)
        graph.bind("schema", SCHEMA)
        graph.bind("ont", ONT)
        graph.bind("rdf", RDF)
        graph.bind("rdfs", "http://www.w3.org/2000/01/rdf-schema#")

        from rdflib import URIRef
        from rdflib.namespace import OWL
        doc_uri = create_document_uri(document_id)
        ontology_uri = URIRef(str(ONT).rstrip("/"))
        graph.add((doc_uri, OWL.imports, ontology_uri))

        # Document metadata
        if document_metadata:
            if 'path' in document_metadata:
                graph.add((doc_uri, SCHEMA.url, sanitize_literal(document_metadata['path'])))
            if 'filename' in document_metadata:
                graph.add((doc_uri, SCHEMA.name, sanitize_literal(document_metadata['filename'])))
            if 'hash' in document_metadata:
                graph.add((doc_uri, KG.hash, sanitize_literal(document_metadata['hash'])))

        # Build entity-name → type map and ensure approved classes exist.
        entity_types: Dict[str, str] = {}
        entity_alternate_names: Dict[str, list] = {}
        if entities:
            for entity in entities:
                name = entity.get('entity', '').strip()
                etype = entity.get('type', 'Other').strip()
                if name:
                    canonical = self.ontology_manager.normalise_type(etype)
                    entity_types[name] = canonical
                    entity_alternate_names[name] = entity.get('alternate_names', [])
                    self.ontology_manager.ensure_approved_class(canonical)

        # All names known to be entities (subjects from extractor + entity list).
        known_entity_names = set(entity_types.keys())

        # Process triples.
        written_entity_uris = set()

        for triple in triples:
            subject = triple.get('subject', '').strip()
            predicate = triple.get('predicate', '').strip()
            obj = triple.get('object', '').strip()

            if not subject or not predicate or not obj:
                continue

            subj_uri = create_entity_uri(subject)
            known_entity_names.add(subject)

            if _is_isa_predicate(predicate):
                # Treat as rdf:type assertion: subject is an instance of obj-class.
                canonical_class = self.ontology_manager.normalise_type(obj)
                class_uri = self.ontology_manager.get_ontology_class_uri(canonical_class)

                if self.ontology_manager.class_is_approved(canonical_class):
                    graph.add((subj_uri, RDF.type, class_uri))
                else:
                    source = (
                        f"{document_metadata.get('filename', document_id)}"
                        f" (triple: {subject} {predicate} {obj})"
                    )
                    self.ontology_manager.propose_class(canonical_class, source)
                    # Still write the rdf:type — it points at the candidate URI.
                    # The class will become formally defined once approved.
                    graph.add((subj_uri, RDF.type, class_uri))

                graph.add((subj_uri, DOC.sourceDocument, doc_uri))
                written_entity_uris.add(subj_uri)

            else:
                # Regular or n-ary relationship triple.
                from .rdf_utils import create_predicate_uri
                pred_uri = create_predicate_uri(predicate)

                if obj in known_entity_names:
                    obj_node = create_entity_uri(obj)
                    graph.add((obj_node, DOC.sourceDocument, doc_uri))
                    written_entity_uris.add(obj_node)
                else:
                    obj_node = Literal(obj)

                scope = triple.get('scope', '').strip()
                strength = triple.get('strength', '').strip()

                if scope:
                    # N-ary triple: reify into intermediate QualifiedRelation node.
                    # Use a deterministic URI so re-runs are idempotent.
                    rel_key = f"{subject}|{predicate}|{obj}|{scope}"
                    rel_hash = hashlib.md5(rel_key.encode()).hexdigest()[:10]
                    rel_uri = URIRef(str(KG) + f"rel_{rel_hash}")
                    graph.add((rel_uri, RDF.type, ONT.QualifiedRelation))
                    graph.add((rel_uri, KG.predicate, Literal(predicate)))
                    graph.add((rel_uri, KG.object, obj_node))
                    scope_node = create_entity_uri(scope)
                    graph.add((rel_uri, KG.scope, scope_node))
                    if strength:
                        graph.add((rel_uri, KG.strength, Literal(strength)))
                    graph.add((rel_uri, DOC.sourceDocument, doc_uri))
                    graph.add((subj_uri, KG.hasQualifiedRelation, rel_uri))
                else:
                    graph.add((subj_uri, pred_uri, obj_node))

                graph.add((subj_uri, DOC.sourceDocument, doc_uri))
                written_entity_uris.add(subj_uri)

        # Ensure every extracted entity has a sourceDocument link, rdf:type,
        # and alternate names — even if never in a relationship triple.
        # Option A: entities typed as 'Other' are flagged for re-typing review.
        kg_filepath = self.output_dir / f"{document_id}.ttl"
        doc_name = document_metadata.get('filename', document_id) if document_metadata else document_id

        for name, canonical_type in entity_types.items():
            uri = create_entity_uri(name)
            graph.add((uri, DOC.sourceDocument, doc_uri))
            type_uri = self.ontology_manager.get_ontology_class_uri(canonical_type)
            # Propose unknown types for review, same as the is_a triple path.
            if not self.ontology_manager.class_is_approved(canonical_type):
                self.ontology_manager.propose_class(canonical_type, doc_name)
            graph.add((uri, RDF.type, type_uri))
            written_entity_uris.add(uri)
            # Write alternate name variants as kg:alternateName literals
            for alt in entity_alternate_names.get(name, []):
                graph.add((uri, KG.alternateName, Literal(alt)))
            # Flag 'Other' typed entities for re-typing (Option A)
            if canonical_type == "Other":
                self.ontology_manager.propose_entity_retyping(
                    entity_uri=str(uri),
                    entity_label=name,
                    source_ttl=str(kg_filepath),
                    source_description=doc_name,
                )

        # Persist KG file.
        filepath = self.output_dir / f"{document_id}.ttl"
        graph.serialize(destination=str(filepath), format='turtle')

        # Persist proposal file (no-op if nothing new).
        doc_name = document_metadata.get('filename', document_id) if document_metadata else document_id
        self.ontology_manager.write_proposed_ontology(generated_by=doc_name)

        return str(filepath), self.ontology_manager.get_proposals()

    def get_knowledge_graph_path(self, document_id: str) -> Optional[str]:
        filepath = self.output_dir / f"{document_id}.ttl"
        return str(filepath) if filepath.exists() else None
