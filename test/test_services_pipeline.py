"""PipelineService unit tests with mocked LLM."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.models import PipelineOptions
from src.services.pipeline import PipelineService
from src.services.progress import CollectingProgressReporter


FIXTURE_TEXT = (
    "Alice works at Acme Corp. Bob manages the engineering team. "
    "Acme Corp sells software products."
)


@pytest.fixture
def fixture_doc(tmp_path):
    doc = tmp_path / "sample.txt"
    doc.write_text(FIXTURE_TEXT, encoding="utf-8")
    return doc


def _mock_entities():
    return [
        {"entity": "Alice", "type": "Person"},
        {"entity": "Acme Corp", "type": "Organization"},
    ]


def _mock_triples():
    return [
        {"subject": "Alice", "predicate": "worksAt", "object": "Acme Corp"},
    ]


@patch("src.services.pipeline.create_benchmark_store")
@patch("src.services.pipeline.MetadataStore")
@patch("src.services.pipeline.TurtleWriter")
@patch("src.services.pipeline.HTMLMarkupGenerator")
def test_pipeline_run_one_chunk(
    mock_html_cls,
    mock_writer_cls,
    mock_meta_cls,
    mock_bench_factory,
    fixture_doc,
    tmp_path,
):
    mock_entity = MagicMock()
    mock_entity.llm_client._provider.model = "test-model"
    mock_entity.extract.return_value = _mock_entities()

    mock_rel = MagicMock()
    mock_rel.extract.return_value = _mock_triples()

    mock_doc = MagicMock()
    mock_doc.process_document.return_value = {
        "filename": "sample.txt",
        "text": FIXTURE_TEXT,
        "word_count": len(FIXTURE_TEXT.split()),
    }
    mock_doc.chunk_text.return_value = [FIXTURE_TEXT]

    mock_writer = MagicMock()
    mock_writer.write_knowledge_graph.return_value = (
        str(tmp_path / "out" / "sample.ttl"),
        [],
    )
    mock_writer_cls.return_value = mock_writer

    mock_html = MagicMock()
    mock_html.generate_markup_from_ttl.return_value = "<html></html>"
    mock_html.save_markup.return_value = str(tmp_path / "sample_markup.html")
    mock_html_cls.return_value = mock_html

    mock_bench = MagicMock()
    mock_bench.start_run.return_value = "run-1"
    mock_bench_factory.return_value = mock_bench

    with patch("src.services.pipeline.load_config") as mock_cfg:
        app = MagicMock()
        app.llm.for_model.return_value = MagicMock(
            chunk_size=800, overlap=100, section_size=1,
        )
        app.get_domain.return_value = MagicMock(description="")
        app.entity_resolution.enabled = False
        app.llm.provider = "mock"
        app.pipeline.max_concurrent_llm_calls = 1
        mock_cfg.return_value = app

        reporter = CollectingProgressReporter()
        result = PipelineService(
            project_root=tmp_path,
            entity_extractor_factory=lambda *a, **k: mock_entity,
            relationship_extractor_factory=lambda *a, **k: mock_rel,
            document_processor_factory=lambda *a, **k: mock_doc,
        ).run(
            PipelineOptions(
                file_path=str(fixture_doc),
                output_dir="out",
                max_chunks=1,
            ),
            reporter=reporter,
        )

    assert result.document_id == "sample"
    assert result.entity_count == 2
    assert result.triple_count == 1
    assert result.kg_path.endswith(".ttl")
    stages = {e.stage for e in reporter.events}
    assert "plan" in stages
    assert "entities" in stages
    assert "relationships" in stages
    assert "write" in stages
    assert "done" in stages
