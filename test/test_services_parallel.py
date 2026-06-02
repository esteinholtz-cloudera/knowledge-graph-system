"""Parallel chunk extraction timing tests."""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.models import PipelineOptions
from src.services.pipeline import PipelineService
from src.services.progress import CollectingProgressReporter

CHUNKS = ["chunk one text", "chunk two text", "chunk three text"]
SLEEP_S = 0.15


def _mock_config(max_concurrent: int):
    app = MagicMock()
    app.llm.for_model.return_value = MagicMock(
        chunk_size=100, overlap=10, section_size=1,
    )
    app.get_domain.return_value = MagicMock(description="")
    app.entity_resolution.enabled = False
    app.llm.provider = "mock"
    app.pipeline.max_concurrent_llm_calls = max_concurrent
    return app


@patch("src.services.pipeline.create_benchmark_store")
@patch("src.services.pipeline.MetadataStore")
@patch("src.services.pipeline.TurtleWriter")
@patch("src.services.pipeline.HTMLMarkupGenerator")
def test_parallel_faster_than_sequential(
    mock_html_cls,
    mock_writer_cls,
    mock_meta_cls,
    mock_bench_factory,
    tmp_path,
):
    def slow_extract(chunk, progress_label=None):
        time.sleep(SLEEP_S)
        return [{"entity": f"E-{progress_label}", "type": "Thing"}]

    mock_entity = MagicMock()
    mock_entity.llm_client._provider.model = "test-model"
    mock_entity.extract.side_effect = slow_extract

    mock_rel = MagicMock()
    mock_rel.extract.side_effect = lambda *a, **k: []

    mock_doc = MagicMock()
    mock_doc.process_document.return_value = {
        "filename": "sample.txt",
        "text": " ".join(CHUNKS),
        "word_count": 10,
    }
    mock_doc.chunk_text.return_value = CHUNKS

    mock_writer = MagicMock()
    mock_writer.write_knowledge_graph.return_value = (str(tmp_path / "out.ttl"), [])
    mock_writer_cls.return_value = mock_writer

    mock_html = MagicMock()
    mock_html.generate_markup_from_ttl.return_value = "<html></html>"
    mock_html.save_markup.return_value = str(tmp_path / "m.html")
    mock_html_cls.return_value = mock_html

    mock_bench = MagicMock()
    mock_bench.start_run.return_value = "run-1"
    mock_bench_factory.return_value = mock_bench

    doc = tmp_path / "sample.txt"
    doc.write_text("x", encoding="utf-8")

    svc = PipelineService(
        project_root=tmp_path,
        entity_extractor_factory=lambda *a, **k: mock_entity,
        relationship_extractor_factory=lambda *a, **k: mock_rel,
        document_processor_factory=lambda *a, **k: mock_doc,
    )

    sequential_budget = len(CHUNKS) * SLEEP_S * 1.9
    parallel_budget = SLEEP_S * 1.9

    with patch("src.services.pipeline.load_config", return_value=_mock_config(1)):
        t0 = time.monotonic()
        svc.run(PipelineOptions(file_path=str(doc), output_dir="out"), CollectingProgressReporter())
        sequential_elapsed = time.monotonic() - t0

    with patch("src.services.pipeline.load_config", return_value=_mock_config(3)):
        t0 = time.monotonic()
        svc.run(PipelineOptions(file_path=str(doc), output_dir="out"), CollectingProgressReporter())
        parallel_elapsed = time.monotonic() - t0

    assert sequential_elapsed >= len(CHUNKS) * SLEEP_S * 0.9
    assert parallel_elapsed < sequential_budget
    assert parallel_elapsed < parallel_budget + 0.1
