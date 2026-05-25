"""
End-to-end pipeline tests for each document in data/documents/.

Each test class:
  1. Redirects KG output to a temporary directory (cleaned up automatically).
  2. Deletes the generated HTML markup and any metadata entry after the class run.

So running this test suite leaves the repository in the same state as before.

Run with:
    uv run pytest test/test_document_pipeline.py -v

These tests call the real LLM (configured in config/config.yaml), so they
require the configured provider to be reachable (e.g. LM Studio running).
"""
import json
import sys
from pathlib import Path
from typing import Optional

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import process_and_extract  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_pipeline(doc_filename: str, tmp_kg_dir: Path) -> dict:
    """Run the full pipeline on a document; KGs go into tmp_kg_dir."""
    doc_path = PROJECT_ROOT / "data" / "documents" / doc_filename
    assert doc_path.exists(), f"Document not found: {doc_path}"
    return process_and_extract(
        file_path=str(doc_path),
        output_dir=str(tmp_kg_dir),
    )


def _remove_metadata_entry(document_id: str):
    """Delete a document's entry from data/metadata.json, if it exists."""
    meta_path = PROJECT_ROOT / "data" / "metadata.json"
    if not meta_path.exists():
        return
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        docs = data.get("documents", {})
        if document_id in docs:
            del docs[document_id]
            data["documents"] = docs
            meta_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except (json.JSONDecodeError, IOError):
        pass


def _cleanup_generated_files(result: Optional[dict]):
    """Remove HTML markup and metadata entry created during a test run."""
    if result is None:
        return
    markup = Path(result["markup_path"])
    if markup.exists():
        markup.unlink()
    _remove_metadata_entry(result["document_id"])


def _assert_ttl_valid(ttl_path: str):
    from rdflib import Graph
    g = Graph()
    g.parse(ttl_path, format="turtle")
    assert len(g) > 0, f"TTL file is empty: {ttl_path}"


def _assert_html_contains_entity(html_path: str):
    html = Path(html_path).read_text(encoding="utf-8")
    assert 'class="entity' in html, "HTML markup contains no entity spans"


# ---------------------------------------------------------------------------
# Skills_description.txt
# ---------------------------------------------------------------------------

class TestSkillsDescription:
    """Pipeline tests for Skills_description.txt."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory, request):
        tmp_kg_dir = tmp_path_factory.mktemp("kg_skills")
        res = _run_pipeline("Skills_description.txt", tmp_kg_dir)
        request.addfinalizer(lambda: _cleanup_generated_files(res))
        return res

    def test_entities_extracted(self, result):
        assert result["entity_count"] > 0, "No entities extracted"

    def test_triples_extracted(self, result):
        assert result["triple_count"] > 0, "No triples extracted"

    def test_ttl_file_exists(self, result):
        assert Path(result["kg_path"]).exists(), "TTL file not created"

    def test_ttl_is_valid_rdf(self, result):
        _assert_ttl_valid(result["kg_path"])

    def test_ttl_contains_rdf_type(self, result):
        from rdflib import Graph
        from rdflib.namespace import RDF
        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        assert list(g.triples((None, RDF.type, None))), "TTL contains no rdf:type assertions"

    def test_html_markup_exists(self, result):
        assert Path(result["markup_path"]).exists(), "HTML markup file not created"

    def test_html_contains_entity_spans(self, result):
        _assert_html_contains_entity(result["markup_path"])

    def test_ontology_proposal_if_new_classes(self, result):
        if result.get("proposals"):
            proposed = PROJECT_ROOT / "data" / "ontology" / "ontology_proposed.ttl"
            assert proposed.exists(), "Proposals reported but ontology_proposed.ttl not created"

    def test_skills_specific_entities(self, result):
        from rdflib import Graph
        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        subjects = {str(s) for s, p, o in g}
        expected = ["SKILL", "Skill", "LLM", "agent", "Agent", "RAG"]
        matched = [f for f in expected if any(f.lower() in s.lower() for s in subjects)]
        assert matched, (
            f"None of {expected} found in TTL subjects.\n"
            f"Subjects (first 20): {sorted(subjects)[:20]}"
        )


# ---------------------------------------------------------------------------
# AgenticAI.txt
# ---------------------------------------------------------------------------

class TestAgenticAI:
    """Pipeline tests for AgenticAI.txt."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory, request):
        tmp_kg_dir = tmp_path_factory.mktemp("kg_agentic")
        res = _run_pipeline("AgenticAI.txt", tmp_kg_dir)
        request.addfinalizer(lambda: _cleanup_generated_files(res))
        return res

    def test_entities_extracted(self, result):
        assert result["entity_count"] > 0, "No entities extracted"

    def test_triples_extracted(self, result):
        assert result["triple_count"] > 0, "No triples extracted"

    def test_ttl_file_exists(self, result):
        assert Path(result["kg_path"]).exists(), "TTL file not created"

    def test_ttl_is_valid_rdf(self, result):
        _assert_ttl_valid(result["kg_path"])

    def test_ttl_contains_rdf_type(self, result):
        from rdflib import Graph
        from rdflib.namespace import RDF
        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        assert list(g.triples((None, RDF.type, None))), "TTL contains no rdf:type assertions"

    def test_html_markup_exists(self, result):
        assert Path(result["markup_path"]).exists(), "HTML markup file not created"

    def test_html_contains_entity_spans(self, result):
        _assert_html_contains_entity(result["markup_path"])

    def test_agentic_ai_specific_entities(self, result):
        from rdflib import Graph
        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        subjects = {str(s) for s, p, o in g}
        expected = ["Agentic", "agentic", "AI", "agent", "Agent", "LLM", "planning"]
        matched = [f for f in expected if any(f.lower() in s.lower() for s in subjects)]
        assert matched, (
            f"None of {expected} found in TTL subjects.\n"
            f"Subjects (first 20): {sorted(subjects)[:20]}"
        )


# ---------------------------------------------------------------------------
# MCP.txt
# ---------------------------------------------------------------------------

class TestMCP:
    """Pipeline tests for MCP.txt."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory, request):
        tmp_kg_dir = tmp_path_factory.mktemp("kg_mcp")
        res = _run_pipeline("MCP.txt", tmp_kg_dir)
        request.addfinalizer(lambda: _cleanup_generated_files(res))
        return res

    def test_entities_extracted(self, result):
        assert result["entity_count"] > 0, "No entities extracted"

    def test_triples_extracted(self, result):
        assert result["triple_count"] > 0, "No triples extracted"

    def test_ttl_file_exists(self, result):
        assert Path(result["kg_path"]).exists(), "TTL file not created"

    def test_ttl_is_valid_rdf(self, result):
        _assert_ttl_valid(result["kg_path"])

    def test_ttl_contains_rdf_type(self, result):
        from rdflib import Graph
        from rdflib.namespace import RDF
        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        assert list(g.triples((None, RDF.type, None))), "TTL contains no rdf:type assertions"

    def test_html_markup_exists(self, result):
        assert Path(result["markup_path"]).exists(), "HTML markup file not created"

    def test_html_contains_entity_spans(self, result):
        _assert_html_contains_entity(result["markup_path"])

    def test_mcp_specific_entities(self, result):
        from rdflib import Graph
        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        subjects = {str(s) for s, p, o in g}
        expected = ["MCP", "Anthropic", "protocol", "Protocol", "LLM", "server", "Server"]
        matched = [f for f in expected if any(f.lower() in s.lower() for s in subjects)]
        assert matched, (
            f"None of {expected} found in TTL subjects.\n"
            f"Subjects (first 20): {sorted(subjects)[:20]}"
        )
