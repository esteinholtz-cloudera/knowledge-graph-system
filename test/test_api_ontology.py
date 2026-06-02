"""Ontology API tests."""
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.app import create_app
from src.ontology.proposal_store import ProposalStore
from src.ontology.sub_taxonomy_service import list_sub_taxonomy_proposals

_MINIMAL_ONT = """\
@prefix ont: <http://example.org/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ont:Thing a owl:Class .
"""


def _setup_ontology(tmp_path):
    ont_dir = tmp_path / "data" / "ontology"
    ont_dir.mkdir(parents=True)
    (ont_dir / "ontology.ttl").write_text(_MINIMAL_ONT, encoding="utf-8")
    from src.ontology.proposal_store import ProposalStore
    store = ProposalStore(
        str(ont_dir / "ontology_proposed.ttl"),
        str(ont_dir / "ontology.ttl"),
    )
    uri = str(store.add_class("TestWidget", comment="from test", proposed_by="unit"))
    store.save()
    return uri


def test_sub_taxonomy_api_approve_reject(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    _setup_ontology(tmp_path)
    store = ProposalStore(
        str(tmp_path / "data" / "ontology" / "ontology_proposed.ttl"),
        str(tmp_path / "data" / "ontology" / "ontology.ttl"),
    )
    bundles = list_sub_taxonomy_proposals(store)
    assert len(bundles) == 1
    proposal_id = bundles[0].id

    listed = client.get("/api/v1/ontology/sub-taxonomy")
    assert listed.status_code == 200
    assert listed.get_json()["count"] == 1

    detail = client.get(f"/api/v1/ontology/sub-taxonomy/{proposal_id}")
    assert detail.status_code == 200
    assert detail.get_json()["label"] == "TestWidget"

    reject = client.post(
        f"/api/v1/ontology/sub-taxonomy/{proposal_id}/approve",
        json={"action": "reject"},
    )
    assert reject.status_code == 200
    assert reject.get_json()["action"] == "reject"


def test_patch_proposal(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True
    client = app.test_client()
    uri = _setup_ontology(tmp_path)
    encoded = quote(uri, safe="")

    status = client.get("/api/v1/ontology/status")
    assert status.status_code == 200
    body = status.get_json()
    assert body["summary"].get("pending", 0) >= 1
    assert len(body.get("sub_taxonomy_proposals", [])) >= 1

    resp = client.patch(
        f"/api/v1/ontology/proposals/{encoded}",
        json={"status": "approved", "parent_class_uri": "http://www.w3.org/2002/07/owl#Thing"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("status") == "approved" or data.get("leaf_class_uri")


def test_wikidata_select_and_parent(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    uri = _setup_ontology(tmp_path)
    encoded = quote(uri, safe="")

    with patch("src.services.ontology.search_wikidata") as mock_search, patch(
        "src.services.ontology.pick_wikidata_entity",
    ) as mock_pick, patch(
        "src.services.ontology.approve_with_wikidata_parent",
    ) as mock_approve:
        mock_search.return_value = [{"qid": "Q42", "label": "Douglas Adams"}]
        mock_pick.return_value = [{"qid": "Q5", "label": "human"}]
        mock_approve.return_value = {
            "proposal": {"uri": uri, "status": "approved"},
            "parent_uri": "http://example.org/ontology/human",
            "new_pending_class": None,
        }

        r = client.post(
            f"/api/v1/ontology/proposals/{encoded}/wikidata-select",
            json={"qid": "Q42"},
        )
        assert r.status_code == 200
        assert r.get_json()["selected_qid"] == "Q42"

        r2 = client.post(
            f"/api/v1/ontology/proposals/{encoded}/wikidata-parent",
            json={"qid": "Q5", "label": "human"},
        )
        assert r2.status_code == 200
        assert r2.get_json()["parent_uri"]


def test_suggest_placement_mocked(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    uri = _setup_ontology(tmp_path)
    encoded = quote(uri, safe="")

    with patch("src.services.ontology.suggest_parents") as mock_suggest:
        mock_suggest.return_value = {"proposals": [{"parent": "ont:Thing", "confidence": 0.9}], "wikidata_hits": []}
        resp = client.post(f"/api/v1/ontology/proposals/{encoded}/suggest-placement", json={})
    assert resp.status_code == 200
    assert resp.get_json()["proposals"]
