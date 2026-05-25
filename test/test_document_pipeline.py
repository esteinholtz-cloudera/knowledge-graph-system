"""
End-to-end pipeline tests for each document in data/documents/.

Each test:
  1. Processes the document through the full pipeline (entity extraction,
     relationship extraction, TTL generation, HTML markup).
  2. Asserts that outputs exist and contain expected content.

These tests call the real LLM (configured in config/config.yaml), so they
require the configured provider to be reachable (e.g. LM Studio running).
Run with:
    uv run pytest test/test_document_pipeline.py -v
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import process_and_extract  # noqa: E402 (project root on path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_pipeline(doc_filename: str) -> dict:
    """Run the full pipeline on a document in data/documents/ and return results."""
    doc_path = PROJECT_ROOT / "data" / "documents" / doc_filename
    assert doc_path.exists(), f"Document not found: {doc_path}"
    result = process_and_extract(
        file_path=str(doc_path),
        output_dir=str(PROJECT_ROOT / "data" / "knowledge_graphs"),
    )
    return result


def _assert_ttl_valid(ttl_path: str):
    """Parse the TTL file and assert it contains at least one triple."""
    from rdflib import Graph

    g = Graph()
    g.parse(ttl_path, format="turtle")
    assert len(g) > 0, f"TTL file is empty: {ttl_path}"


def _assert_html_contains_entity(html_path: str):
    """Assert that the HTML markup contains at least one entity span."""
    html = Path(html_path).read_text(encoding="utf-8")
    assert 'class="entity' in html, "HTML markup contains no entity spans"


# ---------------------------------------------------------------------------
# Skills_description.txt
# ---------------------------------------------------------------------------

class TestSkillsDescription:
    """Pipeline tests for Skills_description.txt."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline("Skills_description.txt")

    def test_entities_extracted(self, result):
        assert result["entity_count"] > 0, "No entities extracted from Skills_description.txt"

    def test_triples_extracted(self, result):
        assert result["triple_count"] > 0, "No triples extracted from Skills_description.txt"

    def test_ttl_file_exists(self, result):
        assert Path(result["kg_path"]).exists(), "TTL file not created"

    def test_ttl_is_valid_rdf(self, result):
        _assert_ttl_valid(result["kg_path"])

    def test_ttl_contains_rdf_type(self, result):
        from rdflib import Graph
        from rdflib.namespace import RDF

        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        types = list(g.triples((None, RDF.type, None)))
        assert len(types) > 0, "TTL contains no rdf:type assertions"

    def test_html_markup_exists(self, result):
        assert Path(result["markup_path"]).exists(), "HTML markup file not created"

    def test_html_contains_entity_spans(self, result):
        _assert_html_contains_entity(result["markup_path"])

    def test_ontology_proposal_if_new_classes(self, result):
        """If the pipeline proposed new ontology classes, the proposal file must exist."""
        if result.get("proposals"):
            proposed = PROJECT_ROOT / "data" / "ontology" / "ontology_proposed.ttl"
            assert proposed.exists(), "Proposals reported but ontology_proposed.ttl not created"

    def test_skills_specific_entities(self, result):
        """At least one of the expected domain entities should appear in the TTL."""
        from rdflib import Graph

        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        subjects = {str(s) for s, p, o in g}
        expected_fragments = ["SKILL", "Skill", "LLM", "agent", "Agent", "RAG"]
        matched = [f for f in expected_fragments if any(f.lower() in s.lower() for s in subjects)]
        assert matched, (
            f"None of the expected domain terms {expected_fragments} found in TTL subjects.\n"
            f"Subjects: {sorted(subjects)[:20]}"
        )


# ---------------------------------------------------------------------------
# AgenticAI.txt
# ---------------------------------------------------------------------------

class TestAgenticAI:
    """Pipeline tests for AgenticAI.txt."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline("AgenticAI.txt")

    def test_entities_extracted(self, result):
        assert result["entity_count"] > 0, "No entities extracted from AgenticAI.txt"

    def test_triples_extracted(self, result):
        assert result["triple_count"] > 0, "No triples extracted from AgenticAI.txt"

    def test_ttl_file_exists(self, result):
        assert Path(result["kg_path"]).exists(), "TTL file not created"

    def test_ttl_is_valid_rdf(self, result):
        _assert_ttl_valid(result["kg_path"])

    def test_ttl_contains_rdf_type(self, result):
        from rdflib import Graph
        from rdflib.namespace import RDF

        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        types = list(g.triples((None, RDF.type, None)))
        assert len(types) > 0, "TTL contains no rdf:type assertions"

    def test_html_markup_exists(self, result):
        assert Path(result["markup_path"]).exists(), "HTML markup file not created"

    def test_html_contains_entity_spans(self, result):
        _assert_html_contains_entity(result["markup_path"])

    def test_agentic_ai_specific_entities(self, result):
        """Core Agentic AI concepts should appear in the extracted graph."""
        from rdflib import Graph

        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        subjects = {str(s) for s, p, o in g}
        expected_fragments = ["Agentic", "agentic", "AI", "agent", "Agent", "LLM", "planning"]
        matched = [f for f in expected_fragments if any(f.lower() in s.lower() for s in subjects)]
        assert matched, (
            f"None of the expected domain terms {expected_fragments} found in TTL subjects.\n"
            f"Subjects: {sorted(subjects)[:20]}"
        )


# ---------------------------------------------------------------------------
# MCP.txt
# ---------------------------------------------------------------------------

class TestMCP:
    """Pipeline tests for MCP.txt."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run_pipeline("MCP.txt")

    def test_entities_extracted(self, result):
        assert result["entity_count"] > 0, "No entities extracted from MCP.txt"

    def test_triples_extracted(self, result):
        assert result["triple_count"] > 0, "No triples extracted from MCP.txt"

    def test_ttl_file_exists(self, result):
        assert Path(result["kg_path"]).exists(), "TTL file not created"

    def test_ttl_is_valid_rdf(self, result):
        _assert_ttl_valid(result["kg_path"])

    def test_ttl_contains_rdf_type(self, result):
        from rdflib import Graph
        from rdflib.namespace import RDF

        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        types = list(g.triples((None, RDF.type, None)))
        assert len(types) > 0, "TTL contains no rdf:type assertions"

    def test_html_markup_exists(self, result):
        assert Path(result["markup_path"]).exists(), "HTML markup file not created"

    def test_html_contains_entity_spans(self, result):
        _assert_html_contains_entity(result["markup_path"])

    def test_mcp_specific_entities(self, result):
        """MCP-specific concepts should appear in the extracted graph."""
        from rdflib import Graph

        g = Graph()
        g.parse(result["kg_path"], format="turtle")
        subjects = {str(s) for s, p, o in g}
        expected_fragments = ["MCP", "Anthropic", "protocol", "Protocol", "LLM", "server", "Server"]
        matched = [f for f in expected_fragments if any(f.lower() in s.lower() for s in subjects)]
        assert matched, (
            f"None of the expected domain terms {expected_fragments} found in TTL subjects.\n"
            f"Subjects: {sorted(subjects)[:20]}"
        )
