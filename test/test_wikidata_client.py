"""Wikidata client label parsing and enrichment."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.ontology.wikidata_client import (
    WikidataClient,
    _normalize_entity_hit,
)


def test_normalize_entity_hit_from_dict():
    hit = _normalize_entity_hit({
        "qid": "Q42",
        "label": "Douglas Adams",
        "description": "English author",
    })
    assert hit == {
        "qid": "Q42",
        "label": "Douglas Adams",
        "description": "English author",
    }


def test_normalize_entity_hit_from_id_alias():
    hit = _normalize_entity_hit({"id": "http://www.wikidata.org/entity/Q5", "title": "human"})
    assert hit["qid"] == "Q5"
    assert hit["label"] == "human"


def test_search_entity_parses_mcp_dict_list():
    client = WikidataClient.__new__(WikidataClient)
    client._tool_call = MagicMock(
        return_value=json.dumps([
            {"qid": "Q42", "label": "Douglas Adams", "description": "author"},
            {"id": "Q5", "title": "human"},
        ])
    )
    client._enrich_labels = MagicMock(side_effect=lambda hits: hits)

    results = client.search_entity("adams")
    assert results[0]["label"] == "Douglas Adams"
    assert results[1]["qid"] == "Q5"
    assert results[1]["label"] == "human"


def test_enrich_labels_uses_wikidata_api():
    client = WikidataClient.__new__(WikidataClient)
    with patch.object(
        client,
        "_labels_via_wikidata_api",
        return_value={"Q42": {"label": "Douglas Adams", "description": "writer"}},
    ):
        hits = client._enrich_labels([{"qid": "Q42", "label": "", "description": ""}])
    assert hits[0]["label"] == "Douglas Adams"
