"""Tests for SubTaxonomyProposal domain and service layer."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from rdflib import Graph

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.ontology.proposal_store import ProposalStore
from src.ontology.sub_taxonomy_service import (
    approve_sub_taxonomy,
    get_sub_taxonomy_proposal,
    list_sub_taxonomy_proposals,
)

_MINIMAL_ONT = """\
@prefix ont: <http://example.org/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ont:Thing a owl:Class .
ont:Technology a owl:Class ;
    rdfs:label "Technology" .
"""


def _store(tmp_path):
    ont_dir = tmp_path / "data" / "ontology"
    ont_dir.mkdir(parents=True)
    (ont_dir / "ontology.ttl").write_text(_MINIMAL_ONT, encoding="utf-8")
    return ProposalStore(
        str(ont_dir / "ontology_proposed.ttl"),
        str(ont_dir / "ontology.ttl"),
    )


def test_list_sub_taxonomy_from_pending_class(tmp_path):
    store = _store(tmp_path)
    uri = str(store.add_class("TestWidget", comment="from test", proposed_by="unit"))
    store.save()

    bundles = list_sub_taxonomy_proposals(store)
    assert len(bundles) == 1
    assert bundles[0].label == "TestWidget"
    assert bundles[0].leaf_class_uri == uri
    assert len(bundles[0].proposed_classes) == 1


def test_needs_typing_creates_leaf_class(tmp_path):
    store = _store(tmp_path)
    store.add_entity_retyping(
        entity_uri="http://example.org/kg/Some_Entity",
        entity_label="Some Entity",
        source_ttl=str(tmp_path / "data" / "knowledge_graphs" / "doc.ttl"),
        proposed_by="unit",
    )
    store.save()

    bundles = list_sub_taxonomy_proposals(store)
    assert len(bundles) == 1
    assert bundles[0].is_needs_typing
    assert bundles[0].entity_uri == "http://example.org/kg/Some_Entity"
    assert bundles[0].leaf_class_uri


def test_approve_sub_taxonomy_reject(tmp_path):
    store = _store(tmp_path)
    uri = str(store.add_class("RejectMe", proposed_by="unit"))
    store.save()
    bundle = list_sub_taxonomy_proposals(store)[0]

    result = approve_sub_taxonomy(store, bundle.id, "reject", Graph())
    assert result.action == "reject"
    assert get_sub_taxonomy_proposal(store, bundle.id) is None


def test_approve_sub_taxonomy_merge(tmp_path):
    store = _store(tmp_path)
    uri = str(store.add_class("NewTool", proposed_by="unit"))
    store.set_subclass_of(uri, "http://example.org/ontology/Technology")
    store.save()
    bundle = list_sub_taxonomy_proposals(store)[0]

    g = Graph()
    g.parse(str(tmp_path / "data" / "ontology" / "ontology.ttl"), format="turtle")
    result = approve_sub_taxonomy(store, bundle.id, "approve", g)
    assert result.action == "approve"
    assert result.merged_classes >= 1
    assert get_sub_taxonomy_proposal(store, bundle.id) is None

    ontology = (tmp_path / "data" / "ontology" / "ontology.ttl").read_text()
    assert "NewTool" in ontology
    assert "subTaxonomyId" not in ontology
    assert "subclassLinkSource" not in ontology


def test_merge_strips_existing_meta_from_ontology(tmp_path):
    store = _store(tmp_path)
    ont_path = tmp_path / "data" / "ontology" / "ontology.ttl"
    ont_path.write_text(
        _MINIMAL_ONT
        + """
@prefix ont_meta: <http://example.org/ontology/meta/> .
ont:Stale a owl:Class ;
    rdfs:label "Stale" ;
    ont_meta:subTaxonomyId "old-bundle-id" .
""",
        encoding="utf-8",
    )
    store = ProposalStore(
        str(tmp_path / "data" / "ontology" / "ontology_proposed.ttl"),
        str(ont_path),
    )
    assert store.merge_approved_into_ontology() == 0
    text = ont_path.read_text()
    assert "subTaxonomyId" not in text
    assert "Stale" in text


def test_approve_sub_taxonomy_retry_after_merge_failure(tmp_path):
    store = _store(tmp_path)
    uri = str(store.add_class("RetryTool", proposed_by="unit"))
    store.save()
    bundle = list_sub_taxonomy_proposals(store)[0]
    g = Graph()
    g.parse(str(tmp_path / "data" / "ontology" / "ontology.ttl"), format="turtle")
    chain = [
        {"label": "RetryTool"},
        {"label": "Thing", "uri": "http://www.w3.org/2002/07/owl#Thing"},
    ]

    with patch.object(type(store), "merge_approved_into_ontology", side_effect=RuntimeError("merge failed")):
        with pytest.raises(RuntimeError):
            approve_sub_taxonomy(store, bundle.id, "approve", g, chain=chain)

    assert get_sub_taxonomy_proposal(store, bundle.id) is not None
    for cls in store.get_all():
        if cls["uri"] == uri:
            assert cls.get("status") == "approved"
            break
    else:
        raise AssertionError("leaf class not found")

    result = approve_sub_taxonomy(store, bundle.id, "approve", g, chain=chain)
    assert result.action == "approve"
    assert result.merged_classes >= 1
