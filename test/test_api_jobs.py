"""API tests for pipeline jobs and SSE."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.app import create_app
from src.services.jobs import JobStore
from src.services.progress import ProgressEvent


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True

    def sync_submit(fn, job_id, *args, **kwargs):
        fn(job_id, *args, **kwargs)

    app.extensions["job_runner"].submit = sync_submit
    return app.test_client()


def test_pipeline_job_requires_file_path(client):
    resp = client.post("/api/v1/jobs/pipeline", json={})
    assert resp.status_code == 400


@patch("src.api.routes.jobs.execute_pipeline_job")
def test_pipeline_job_sse_done(mock_execute, client, tmp_path):
    doc = tmp_path / "data" / "documents" / "sample.txt"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("hello world", encoding="utf-8")

    def fake_execute(job_id, params, store, root):
        store.update_status(job_id, "running")
        store.append_event(job_id, ProgressEvent(stage="entities", message="chunk 1"))
        store.update_status(
            job_id,
            "succeeded",
            result={"document_id": "sample", "stage": "done"},
        )
        store.append_event(job_id, ProgressEvent(stage="done"))

    mock_execute.side_effect = fake_execute

    resp = client.post(
        "/api/v1/jobs/pipeline",
        json={"file_path": "data/documents/sample.txt"},
    )
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    events_resp = client.get(f"/api/v1/jobs/{job_id}/events")
    body = events_resp.get_data(as_text=True)
    assert "event: progress" in body
    assert "entities" in body
    assert "event: done" in body
    assert "event: job_failed" not in body

    job_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert job_resp.get_json()["status"] == "succeeded"


def test_precheck_endpoint(client):
    with patch("src.api.routes.health.HealthService") as mock_health:
        mock_health.return_value.check.return_value = type(
            "R", (), {"ok": True, "checks": []},
        )()
        resp = client.get("/api/v1/health/precheck")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_config_endpoint(client):
    resp = client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "llm" in data
    assert "domains" in data
    assert "OPENAI_API_KEY" not in json.dumps(data)
