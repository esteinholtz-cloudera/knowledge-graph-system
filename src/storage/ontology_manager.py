"""Ontology manager for loading and managing the local ontology."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .rdf_utils import ONT


# Predicates defined in the default ontology — always considered approved.
_DEFAULT_CLASSES = {
    'Person', 'Organization', 'Location', 'Technology',
    'Concept', 'Product', 'Event', 'Date', 'Other',
}

# Normalise LLM-emitted type strings to canonical class names.
_TYPE_ALIASES: Dict[str, str] = {
    'person': 'Person',
    'organisation': 'Organization',
    'organization': 'Organization',
    'location': 'Location',
    'technology': 'Technology',
    'concept': 'Concept',
    'product': 'Product',
    'event': 'Event',
    'date': 'Date',
    'other': 'Other',
}

# Predicates that express is-a / instance-of semantics.
ISA_PREDICATES = {'is', 'isa', 'is_a', 'is a', 'type', 'typeof', 'instanceof', 'a'}


class OntologyManager:
    """Manage local ontology and collect proposals for human review."""

    def __init__(self, ontology_dir: str = "data/ontology"):
        self.ontology_dir = Path(ontology_dir)
        self.ontology_dir.mkdir(parents=True, exist_ok=True)
        self.ontology_file = self.ontology_dir / "ontology.ttl"
        self.proposed_file = self.ontology_dir / "ontology_proposed.ttl"
        self.graph = Graph()
        self._proposals: Dict[str, Dict] = {}  # class_name -> {uri, label, sources}
        self._load_ontology()
        self._load_existing_proposals()

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------

    def _load_ontology(self):
        """Load ontology from file or create default."""
        if self.ontology_file.exists():
            self.graph.parse(str(self.ontology_file), format='turtle')
        else:
            self._create_default_ontology()
            self._save_ontology()

    def _load_existing_proposals(self):
        """Seed _proposals from any existing ontology_proposed.ttl.

        This ensures a successive pipeline run does not overwrite unapproved
        proposals from a previous run — new proposals are merged in.
        """
        if not self.proposed_file.exists():
            return
        try:
            prior = Graph()
            prior.parse(str(self.proposed_file), format='turtle')
            for class_uri, _, _ in prior.triples((None, RDF.type, OWL.Class)):
                # Only load classes that are NOT already in the approved ontology
                if (class_uri, RDF.type, OWL.Class) in self.graph:
                    continue
                label = str(next(prior.objects(class_uri, RDFS.label), class_uri))
                comment = str(next(prior.objects(class_uri, RDFS.comment), ""))
                sources = [s.strip() for s in comment.replace("Proposed from: ", "").split(";") if s.strip()] if comment else []
                if label not in self._proposals:
                    self._proposals[label] = {
                        'uri': class_uri,
                        'label': label,
                        'sources': sources,
                    }
        except Exception:
            pass  # Corrupt or unreadable proposed file — start fresh

    def _create_default_ontology(self):
        """Create default OWL ontology with base entity-type classes."""
        self.graph.bind("ont", ONT)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        self.graph.bind("owl", OWL)

        base_classes = {
            'Person':       'A human being or individual',
            'Organization': 'A company, institution, or group',
            'Location':     'A geographical place or location',
            'Technology':   'A technology, tool, or platform',
            'Concept':      'An abstract concept or idea',
            'Product':      'A product or service',
            'Event':        'An event or occurrence',
            'Date':         'A date or time period',
            'Other':        'Other type of entity',
        }
        for name, comment in base_classes.items():
            uri = ONT[name]
            self.graph.add((uri, RDF.type, OWL.Class))
            self.graph.add((uri, RDFS.label, Literal(name)))
            self.graph.add((uri, RDFS.comment, Literal(comment)))

    def _save_ontology(self):
        """Persist the approved ontology to file."""
        self.graph.serialize(destination=str(self.ontology_file), format='turtle')

    # ------------------------------------------------------------------
    # Class resolution
    # ------------------------------------------------------------------

    def normalise_type(self, entity_type: str) -> str:
        """Map a raw LLM type string to a canonical class name."""
        stripped = entity_type.strip()
        return _TYPE_ALIASES.get(stripped.lower(), stripped.title())

    def get_ontology_class_uri(self, entity_type: str) -> URIRef:
        """Return the ONT URI for a (possibly non-normalised) type name."""
        canonical = self.normalise_type(entity_type)
        sanitized = quote(canonical.replace(' ', '_'), safe='')
        return ONT[sanitized]

    def class_is_approved(self, entity_type: str) -> bool:
        """Return True if the class URI already exists in the approved ontology."""
        uri = self.get_ontology_class_uri(entity_type)
        return (uri, RDF.type, OWL.Class) in self.graph

    def ensure_approved_class(self, entity_type: str):
        """
        For types in the base set that may be missing from an existing ontology.ttl,
        add them silently (they are approved by definition).
        Unknown types are not written here — use propose_class() instead.
        """
        canonical = self.normalise_type(entity_type)
        if canonical in _DEFAULT_CLASSES and not self.class_is_approved(canonical):
            uri = ONT[canonical]
            self.graph.add((uri, RDF.type, OWL.Class))
            self.graph.add((uri, RDFS.label, Literal(canonical)))
            self._save_ontology()

    # ------------------------------------------------------------------
    # Proposal collection
    # ------------------------------------------------------------------

    def propose_class(
        self,
        entity_type: str,
        source_description: Optional[str] = None,
    ):
        """
        Register a candidate new ontology class for human review.

        Nothing is written to ontology.ttl.  Call write_proposed_ontology()
        after all processing is done to produce ontology_proposed.ttl.
        """
        canonical = self.normalise_type(entity_type)
        if self.class_is_approved(canonical):
            return  # Already in the approved ontology — no proposal needed.

        if canonical not in self._proposals:
            self._proposals[canonical] = {
                'uri': self.get_ontology_class_uri(canonical),
                'label': canonical,
                'sources': [],
            }
        if source_description:
            self._proposals[canonical]['sources'].append(source_description)

    def has_proposals(self) -> bool:
        return bool(self._proposals)

    def get_proposals(self) -> List[Dict]:
        return list(self._proposals.values())

    def write_proposed_ontology(self, generated_by: Optional[str] = None):
        """
        Write ontology_proposed.ttl in DIFFERENTIAL format.

        Contains ONLY new additions with review_status metadata.
        Delegates to ProposalStore which handles accumulation across runs.
        """
        if not self._proposals:
            return  # Nothing to write; don't delete any pre-existing proposals

        from src.ontology.proposal_store import ProposalStore
        store = ProposalStore(
            str(self.proposed_file),
            str(self.ontology_file),
        )
        for label, class_info in self._proposals.items():
            sources = class_info.get('sources', [])
            comment = ("Proposed from: " + "; ".join(sources)) if sources else ""
            # Only add if not already in the store
            existing = {c['label'] for c in store.get_all()}
            if label not in existing:
                store.add_class(
                    label=label,
                    comment=comment,
                    proposed_by=generated_by or "",
                )
        store.save()

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def approve_proposed_ontology(self) -> int:
        """
        Approve all pending proposals — merges them into ontology.ttl.

        Uses ProposalStore to merge only approved items (not replace the whole file).
        Returns the number of new classes merged.
        """
        if not self.proposed_file.exists():
            return 0
        from src.ontology.proposal_store import ProposalStore
        store = ProposalStore(str(self.proposed_file), str(self.ontology_file))
        # Mark all pending as approved (bulk approve)
        for cls in store.get_pending():
            store.set_status(cls['uri'], 'approved')
        store.save()
        merged = store.merge_approved_into_ontology()
        # Reload the approved graph
        self.graph = Graph()
        if self.ontology_file.exists():
            self.graph.parse(str(self.ontology_file), format='turtle')
        return merged

    # ------------------------------------------------------------------
    # Legacy helpers
    # ------------------------------------------------------------------

    def get_ontology_file_path(self) -> str:
        return str(self.ontology_file)

    def get_ontology_graph(self) -> Graph:
        return self.graph
