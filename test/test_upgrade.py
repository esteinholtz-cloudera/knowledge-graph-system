"""Tests for the token-conservative upgrade funnel (deterministic stages).

Covers the free, no-LLM stages end to end: HTML-table extraction, the keyword
gate, fact dedupe, and TTL emission. The LLM pass is exercised only with a stub
so the suite stays offline.
"""
from pathlib import Path

from rdflib import Graph

from src.extraction.upgrade.llm_pass import UpgradeLLMExtractor
from src.extraction.upgrade.runner import run_upgrade_extraction
from src.extraction.upgrade.schema import UpgradeFact, dedupe_facts, gate_chunks, is_upgrade_url
from src.extraction.upgrade.scoping import html_to_text
from src.extraction.upgrade.tables import facts_from_html
from src.extraction.upgrade.writer import build_graph, write_upgrade_ttl

_FROM_TO_HTML = """
<html><body>
<h1>Supported upgrade paths</h1>
<table>
  <tr><th>From version</th><th>To version</th></tr>
  <tr><td>CDP 7.1.7</td><td>CDP 7.1.9</td></tr>
  <tr><td>CDP 7.1.8</td><td>CDP 7.1.9</td></tr>
</table>
</body></html>
"""

_MATRIX_HTML = """
<table>
  <tr><th>Component compatibility</th><th>CDP 7.1.9</th><th>CDP 7.2.0</th></tr>
  <tr><td>Hive 3.1</td><td>Yes</td><td>No</td></tr>
  <tr><td>Spark 3.3</td><td>Supported</td><td>Yes</td></tr>
</table>
"""


def test_from_to_table_yields_upgrades_to():
    facts = facts_from_html(_FROM_TO_HTML, source="http://docs/x")
    pairs = {(f.subject, f.predicate, f.object) for f in facts}
    assert ("CDP 7.1.7", "upgradesTo", "CDP 7.1.9") in pairs
    assert ("CDP 7.1.8", "upgradesTo", "CDP 7.1.9") in pairs
    assert all(f.origin == "table" for f in facts)


def test_matrix_table_yields_compatible_for_supported_cells_only():
    facts = facts_from_html(_MATRIX_HTML, source="s")
    pairs = {(f.subject, f.predicate, f.object) for f in facts}
    assert ("Hive 3.1", "isCompatibleWith", "CDP 7.1.9") in pairs
    assert ("Spark 3.3", "isCompatibleWith", "CDP 7.2.0") in pairs
    assert ("Hive 3.1", "isCompatibleWith", "CDP 7.2.0") not in pairs  # cell was "No"


def test_unrelated_table_yields_nothing():
    html = "<table><tr><th>Name</th><th>Role</th></tr><tr><td>Ann</td><td>Admin</td></tr></table>"
    assert facts_from_html(html) == []


def test_url_scope_filter():
    assert is_upgrade_url("https://docs.cloudera.com/cdp/latest/upgrade/topics/x.html")
    assert is_upgrade_url("https://docs.cloudera.com/release-notes/foo.html")
    assert not is_upgrade_url("https://docs.cloudera.com/cdp/latest/overview/intro.html")


def test_gate_chunks_drops_no_signal_chunks():
    chunks = ["The sky is blue.", "Upgrade from 7.1.7 to 7.1.9 is supported."]
    gated = gate_chunks(chunks)
    assert gated == ["Upgrade from 7.1.7 to 7.1.9 is supported."]


def test_dedupe_drops_invalid_and_exact_repeats():
    facts = [
        UpgradeFact("A", "upgradesTo", "B"),
        UpgradeFact("a", "upgradesTo", "b"),  # case-variant duplicate
        UpgradeFact("A", "bogusPredicate", "B"),  # invalid predicate
        UpgradeFact("", "upgradesTo", "B"),  # empty subject
    ]
    assert len(dedupe_facts(facts)) == 1


def test_html_to_text_strips_scripts():
    text = html_to_text("<html><head><style>x{}</style></head><body><p>Hello</p><script>bad()</script></body></html>")
    assert "Hello" in text
    assert "bad()" not in text and "x{}" not in text


def test_writer_emits_typed_provenanced_ttl():
    facts = [
        UpgradeFact("CDP 7.1.7", "upgradesTo", "CDP 7.1.9", source="http://docs/x"),
        UpgradeFact("CDP 7.1.9", "requiresPrerequisite", "JDK 17", source="http://docs/x"),
    ]
    graph = build_graph(facts)
    serialized = graph.serialize(format="turtle")
    assert "upgradesTo" in serialized
    assert "SoftwareVersion" in serialized  # digit-bearing labels typed as versions
    assert "JDK 17" in serialized  # literal-object predicate kept as literal
    assert isinstance(graph, Graph) and len(graph) > 0


class _StubExtractor(UpgradeLLMExtractor):
    def __init__(self):
        pass  # skip LLM client construction

    def extract(self, text, source="", progress_label=None):
        return [UpgradeFact("Feature X", "deprecatedIn", "CDP 7.2.0", source=source, origin="llm")]


def test_runner_combines_table_and_llm_facts(tmp_path):
    html_file = tmp_path / "page.html"
    html_file.write_text(_FROM_TO_HTML + "<p>Upgrade note: Feature X is deprecated.</p>", encoding="utf-8")
    out = tmp_path / "upgrade.ttl"

    result = run_upgrade_extraction(
        [str(html_file)], str(out), use_llm=True, extractor=_StubExtractor()
    )

    assert result.pages == 1
    assert result.table_facts >= 2  # two upgrade paths
    assert result.llm_facts >= 1  # stubbed deprecation
    assert Path(result.output_path).exists()
    g = Graph()
    g.parse(out, format="turtle")
    assert len(g) > 0


def test_runner_no_llm_is_deterministic(tmp_path):
    html_file = tmp_path / "page.html"
    html_file.write_text(_FROM_TO_HTML, encoding="utf-8")
    out = tmp_path / "upgrade.ttl"
    result = run_upgrade_extraction([str(html_file)], str(out), use_llm=False)
    assert result.llm_facts == 0
    assert result.chunks_gated == 0
    assert result.table_facts >= 2
