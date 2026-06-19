"""Tests for markup anchor ids and link resolution."""
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.document.markup_anchors import (
    anchor_exists_in_html,
    document_id_from_proposal_text,
    entity_markup_anchor,
    source_document_for_entity_label,
)
from src.document.html_markup import HTMLMarkupGenerator
from src.services.markup_link import MarkupLinkService


def test_entity_markup_anchor_from_uri():
    anchor = entity_markup_anchor(
        "http://example.org/kg/Industrial_Revolution",
        "Industrial Revolution",
    )
    assert anchor == "entity-industrial-revolution"


def test_entity_markup_anchor_occurrence():
    anchor = entity_markup_anchor(
        "http://example.org/kg/Paris",
        "Paris",
        occurrence=2,
    )
    assert anchor == "entity-paris-2"


def test_markup_spans_include_anchor_ids():
    gen = HTMLMarkupGenerator()
    text = "Marie Curie lived in Paris. Paris is a city."
    entities = [{"entity": "Paris", "type": "Location", "uri": "http://example.org/kg/Paris"}]
    html_doc = gen.generate_markup(text, entities, "sample.txt")
    assert 'id="entity-paris"' in html_doc
    assert 'id="entity-paris-1"' in html_doc
    assert anchor_exists_in_html(html_doc, "entity-paris")


def test_markup_link_resolves_from_source_ttl(tmp_path):
    docs = tmp_path / "data" / "documents"
    kgs = tmp_path / "data" / "knowledge_graphs"
    docs.mkdir(parents=True)
    kgs.mkdir(parents=True)
    (kgs / "sample.ttl").write_text("@prefix kg: <http://example.org/kg/> .\n", encoding="utf-8")
    markup = docs / "sample_markup.html"
    markup.write_text(
        '<html><body><span id="entity-widget" class="entity">Widget</span></body></html>',
        encoding="utf-8",
    )

    svc = MarkupLinkService(tmp_path)
    result = svc.resolve_for_proposal(
        entity_uri="http://example.org/kg/Widget",
        entity_label="Widget",
        source_ttl=str(kgs / "sample.ttl"),
    )
    assert result.available is True
    assert result.document_id == "sample"
    assert result.anchor == "entity-widget"


def test_document_id_from_proposed_from_comment():
    assert document_id_from_proposal_text("Proposed from: cr-installation.pdf") == "cr-installation"


def test_markup_link_from_class_comment(tmp_path):
    docs = tmp_path / "data" / "documents"
    kgs = tmp_path / "data" / "knowledge_graphs"
    docs.mkdir(parents=True)
    kgs.mkdir(parents=True)
    from rdflib import Graph, URIRef
    from rdflib.namespace import RDF

    from src.storage.rdf_utils import KG, create_entity_uri

    entity = create_entity_uri("Widget")
    class_uri = URIRef("http://example.org/ontology/NewType")
    graph = Graph()
    graph.add((entity, RDF.type, class_uri))
    graph.serialize(destination=str(kgs / "demo.ttl"), format="turtle")

    (docs / "demo_markup.html").write_text(
        '<html><body><span class="entity">'
        '<a href="http://example.org/kg/Widget">Widget</a></span></body></html>',
        encoding="utf-8",
    )
    svc = MarkupLinkService(tmp_path)
    result = svc.resolve_for_proposal(
        entity_uri=None,
        entity_label="NewType",
        source_ttl=None,
        class_comment="Proposed from: demo.txt",
        leaf_class_uri="http://example.org/ontology/NewType",
    )
    assert result.available is True
    assert result.document_id == "demo"
    assert result.entity_label == "Widget"


def test_source_document_for_entity_label(tmp_path):
    pytest.importorskip("rdflib")
    from rdflib import Graph, Literal, URIRef
    from rdflib.namespace import RDF

    from src.storage.rdf_utils import DOC, KG, ONT, create_entity_uri

    kgs = tmp_path / "data" / "knowledge_graphs"
    kgs.mkdir(parents=True)
    g = Graph()
    g.bind("kg", KG)
    g.bind("doc", DOC)
    g.bind("ont", ONT)
    entity = create_entity_uri("Widget")
    doc = URIRef(str(DOC) + "sample-doc")
    g.add((entity, RDF.type, URIRef(str(ONT) + "Product")))
    g.add((entity, DOC.sourceDocument, doc))
    g.add((doc, RDF.type, URIRef("http://schema.org/CreativeWork")))
    g.serialize(destination=str(kgs / "sample-doc.ttl"), format="turtle")

    assert source_document_for_entity_label("Widget", tmp_path) == "sample-doc"
