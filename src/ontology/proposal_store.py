"""
Differential ontology proposal store.

ontology_proposed.ttl contains ONLY the new triples to be added (not the full
ontology). Each proposed class has a review_status annotation:
  ont_meta:reviewStatus "pending" | "approved" | "rejected"

Approval MERGES the approved triples into ontology.ttl.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

ONT = Namespace("http://example.org/ontology/")
ONT_META = Namespace("http://example.org/ontology/meta/")
WD = Namespace("http://www.wikidata.org/entity/")

REVIEW_STATUS = ONT_META.reviewStatus
PROPOSED_BY = ONT_META.proposedBy

STATUS_PENDING = Literal("pending")
STATUS_APPROVED = Literal("approved")
STATUS_REJECTED = Literal("rejected")

_HEADER = """\
# ontology_proposed.ttl — DIFFERENTIAL additions only
# Generated: {ts}
#
# This file contains ONLY the new triples to be added to ontology.ttl.
# It does NOT replace the existing ontology.
#
# Review interactively:  python main.py ontology review
# Bulk approve all:      python main.py ontology approve
# Show status:           python main.py ontology status

"""


class ProposalStore:
    """Read and write the differential ontology proposal file."""

    def __init__(
        self,
        proposal_file: str,
        ontology_file: str,
    ):
        self.proposal_file = Path(proposal_file)
        self.ontology_file = Path(ontology_file)
        self._graph = Graph()
        self._bind_namespaces()
        if self.proposal_file.exists():
            self._graph.parse(str(self.proposal_file), format="turtle")

    def _bind_namespaces(self):
        self._graph.bind("ont", ONT)
        self._graph.bind("ont_meta", ONT_META)
        self._graph.bind("owl", OWL)
        self._graph.bind("rdfs", RDFS)
        self._graph.bind("wd", WD)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_pending(self) -> List[Dict]:
        """Return proposed classes with status 'pending'."""
        return self._get_by_status(STATUS_PENDING)

    def get_all(self) -> List[Dict]:
        """Return all proposed classes regardless of status."""
        results = []
        for cls in set(self._graph.subjects(RDF.type, OWL.Class)):
            if str(cls).startswith(str(ONT)):
                results.append(self._load_class(cls))
        return results

    def _get_by_status(self, status: Literal) -> List[Dict]:
        return [
            self._load_class(s)
            for s, p, o in self._graph.triples((None, REVIEW_STATUS, status))
            if str(s).startswith(str(ONT))
        ]

    def _load_class(self, uri: URIRef) -> Dict:
        g = self._graph
        label = str(next(g.objects(uri, RDFS.label), uri.split("/")[-1]))
        comment = str(next(g.objects(uri, RDFS.comment), ""))
        status = str(next(g.objects(uri, REVIEW_STATUS), STATUS_PENDING))
        proposed_by = str(next(g.objects(uri, PROPOSED_BY), ""))
        subclass_of = [str(o) for _, _, o in g.triples((uri, RDFS.subClassOf, None))]
        equiv_class = [str(o) for _, _, o in g.triples((uri, OWL.equivalentClass, None))]
        return {
            "uri": str(uri),
            "label": label,
            "comment": comment,
            "status": status,
            "proposed_by": proposed_by,
            "subclass_of": subclass_of,
            "equivalent_class": equiv_class,
        }

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def add_class(
        self,
        label: str,
        comment: str = "",
        proposed_by: str = "",
        status: str = "pending",
    ) -> URIRef:
        """Add a proposed class. Returns its URI."""
        from urllib.parse import quote
        local = quote(label.strip().replace(" ", "_"), safe="")
        uri = ONT[local]
        g = self._graph
        g.add((uri, RDF.type, OWL.Class))
        g.add((uri, RDFS.label, Literal(label)))
        if comment:
            g.add((uri, RDFS.comment, Literal(comment)))
        if proposed_by:
            g.add((uri, PROPOSED_BY, Literal(proposed_by)))
        g.set((uri, REVIEW_STATUS, Literal(status)))
        return uri

    def set_subclass_of(self, class_uri: str, parent_uri: str):
        """Set rdfs:subClassOf for a class, replacing any existing value."""
        uri = URIRef(class_uri)
        # Remove existing subClassOf
        for triple in list(self._graph.triples((uri, RDFS.subClassOf, None))):
            self._graph.remove(triple)
        self._graph.add((uri, RDFS.subClassOf, URIRef(parent_uri)))

    def set_equivalent_class(self, class_uri: str, equiv_uri: str):
        """Add owl:equivalentClass (Wikidata alignment)."""
        self._graph.add((URIRef(class_uri), OWL.equivalentClass, URIRef(equiv_uri)))

    def set_status(self, class_uri: str, status: str):
        self._graph.set((URIRef(class_uri), REVIEW_STATUS, Literal(status)))

    def save(self):
        """Serialise the proposal graph to the proposal file."""
        ttl = self._graph.serialize(format="turtle")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.proposal_file.parent.mkdir(parents=True, exist_ok=True)
        self.proposal_file.write_text(
            _HEADER.format(ts=ts) + ttl, encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Approval (merge into ontology.ttl)
    # ------------------------------------------------------------------

    def merge_approved_into_ontology(self) -> int:
        """
        Merge all approved classes into ontology.ttl.
        Returns the number of classes merged.
        """
        ontology = Graph()
        if self.ontology_file.exists():
            ontology.parse(str(self.ontology_file), format="turtle")

        approved = self._get_by_status(STATUS_APPROVED)
        if not approved:
            return 0

        for cls_info in approved:
            uri = URIRef(cls_info["uri"])
            # Copy all triples for this class except meta triples
            for s, p, o in self._graph.triples((uri, None, None)):
                if p in (REVIEW_STATUS, PROPOSED_BY):
                    continue
                ontology.add((s, p, o))

        ontology.serialize(destination=str(self.ontology_file), format="turtle")

        # Mark merged classes as removed from proposals
        for cls_info in approved:
            uri = URIRef(cls_info["uri"])
            for triple in list(self._graph.triples((uri, None, None))):
                self._graph.remove(triple)

        # If no pending classes remain, remove the proposal file
        if not self.get_pending() and not self._get_by_status(STATUS_PENDING):
            if self.proposal_file.exists():
                self.proposal_file.unlink()
        else:
            self.save()

        return len(approved)

    def status_summary(self) -> Dict[str, int]:
        """Return counts by status."""
        all_classes = self.get_all()
        counts: Dict[str, int] = {"pending": 0, "approved": 0, "rejected": 0}
        for cls in all_classes:
            s = cls.get("status", "pending")
            counts[s] = counts.get(s, 0) + 1
        return counts
