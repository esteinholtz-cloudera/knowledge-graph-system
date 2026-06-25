"""Emit upgrade facts to a clean, provenance-bearing Turtle file (stage 6).

Deliberately independent of the heavyweight ``TurtleWriter`` (which runs the
ontology-proposal workflow): the upgrade funnel targets a fixed two-class
ontology, so emission is a direct, side-effect-free serialization.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from ...storage.rdf_utils import DOC, KG, ONT, create_entity_uri, create_predicate_uri
from .schema import ENTITY_OBJECT_PREDICATES, UpgradeFact, dedupe_facts

_VERSION_HINT = re.compile(r"\d")


def _type_uri(name: str) -> URIRef:
    """Type a surface string: anything containing a digit is a version."""
    return ONT.SoftwareVersion if _VERSION_HINT.search(name) else ONT.Product


def _source_node(source: str) -> URIRef:
    if source.startswith(("http://", "https://")):
        return URIRef(source)
    return DOC[source.replace(" ", "_")]


def _add_entity(graph: Graph, name: str, source: str) -> URIRef:
    uri = create_entity_uri(name)
    graph.add((uri, RDF.type, _type_uri(name)))
    graph.add((uri, RDFS.label, Literal(name)))
    if source:
        graph.add((uri, DOC.sourceDocument, _source_node(source)))
    return uri


def _bind_namespaces(graph: Graph) -> None:
    graph.bind("kg", KG)
    graph.bind("ont", ONT)
    graph.bind("doc", DOC)
    graph.bind("rdfs", RDFS)


def build_graph(facts: Iterable[UpgradeFact]) -> Graph:
    graph = Graph()
    _bind_namespaces(graph)
    for fact in dedupe_facts(facts):
        subj = _add_entity(graph, fact.subject, fact.source)
        pred = create_predicate_uri(fact.predicate)
        if fact.predicate in ENTITY_OBJECT_PREDICATES:
            obj = _add_entity(graph, fact.object, fact.source)
        else:
            obj = Literal(fact.object)
        graph.add((subj, pred, obj))
    return graph


def write_upgrade_ttl(facts: Iterable[UpgradeFact], output_path: str) -> str:
    """Serialize deduped upgrade facts to ``output_path``; return that path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph = build_graph(facts)
    graph.serialize(destination=str(path), format="turtle")
    return str(path)
