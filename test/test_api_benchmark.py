"""Benchmark API route tests."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.app import create_app
from src.services.models import TableResult


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True
    return app.test_client()


@patch("src.api.routes.benchmark._svc.get_view")
def test_benchmark_runs_returns_table_rows(mock_get_view, client):
    mock_get_view.return_value = TableResult(
        columns=["started", "document"],
        rows=[["2026-06-18 16:22", "sample.txt"]],
        text="",
    )

    resp = client.get("/api/v1/benchmark/runs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["columns"] == ["started", "document"]
    assert data["rows"] == [["2026-06-18 16:22", "sample.txt"]]
    assert "available" in data


def test_benchmark_runs_live_when_duckdb_installed(client):
    duckdb = pytest.importorskip("duckdb")
    del duckdb  # used only for skip check

    resp = client.get("/api/v1/benchmark/runs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert isinstance(data["columns"], list)
    assert isinstance(data["rows"], list)
    # Shape is stable even when the DB is empty.
    if data["rows"]:
        assert len(data["rows"][0]) == len(data["columns"])
