"""Normalize API tests."""
import sys
from pathlib import Path

import yaml

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.app import create_app


def test_normalize_map_patch_and_apply_dry_run(tmp_path):
    kg_dir = tmp_path / "data" / "knowledge_graphs"
    kg_dir.mkdir(parents=True)
    (kg_dir / "doc.ttl").write_text(
        "@prefix kg: <http://example.org/kg/> .\n"
        "kg:a kg:worksAt kg:b .\n",
        encoding="utf-8",
    )
    ont_dir = tmp_path / "data" / "ontology"
    ont_dir.mkdir(parents=True)
    (ont_dir / "ontology.ttl").write_text(
        "@prefix ont: <http://example.org/ontology/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ont:Thing a owl:Class .\n",
        encoding="utf-8",
    )
    map_path = tmp_path / "data" / "predicate_map.yaml"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(yaml.dump({
        "mappings": [{
            "canonical": "worksAt",
            "variants": ["worksAt", "works_at"],
            "reviewed": False,
        }],
    }), encoding="utf-8")

    client = create_app(tmp_path).test_client()

    resp = client.get("/api/v1/normalize/map")
    assert resp.status_code == 200
    assert len(resp.get_json()["mappings"]) == 1

    resp = client.patch(
        "/api/v1/normalize/map/groups/worksAt",
        json={"reviewed": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["reviewed"] is True

    resp = client.post(
        "/api/v1/normalize/apply",
        json={"dry_run": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["dry_run"] is True
