"""Pipeline cancellation tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.jobs import JobCancelled
from src.services.models import PipelineOptions
from src.services.pipeline import PipelineService
from src.services.progress import CollectingProgressReporter


@patch("src.services.pipeline.create_benchmark_store")
@patch("src.services.pipeline.MetadataStore")
@patch("src.services.pipeline.TurtleWriter")
@patch("src.services.pipeline.HTMLMarkupGenerator")
def test_cancel_before_relationships(
    mock_html_cls,
    mock_writer_cls,
    mock_meta_cls,
    mock_bench_factory,
    tmp_path,
):
    mock_entity = MagicMock()
    mock_entity.llm_client._provider.model = "test-model"
    mock_entity.extract.return_value = [{"entity": "Alice", "type": "Person"}]

    mock_rel = MagicMock()
    mock_doc = MagicMock()
    mock_doc.process_document.return_value = {
        "filename": "sample.txt", "text": "a b", "word_count": 2,
    }
    mock_doc.chunk_text.return_value = ["chunk"]

    mock_bench = MagicMock()
    mock_bench.start_run.return_value = "run-1"
    mock_bench_factory.return_value = mock_bench

    doc = tmp_path / "sample.txt"
    doc.write_text("hello", encoding="utf-8")

    cancelled = {"flag": False}

    def cancel_check():
        return cancelled["flag"]

    with patch("src.services.pipeline.load_config") as mock_cfg:
        app = MagicMock()
        app.llm.for_model.return_value = MagicMock(chunk_size=100, overlap=10, section_size=1, chunk_strategy="recursive")
        app.get_domain.return_value = MagicMock(description="")
        app.entity_resolution.enabled = False
        app.llm.provider = "mock"
        app.pipeline.max_concurrent_llm_calls = 1
        mock_cfg.return_value = app

        svc = PipelineService(
            project_root=tmp_path,
            entity_extractor_factory=lambda *a, **k: mock_entity,
            relationship_extractor_factory=lambda *a, **k: mock_rel,
            document_processor_factory=lambda *a, **k: mock_doc,
        )
        cancelled["flag"] = True
        with pytest.raises(JobCancelled):
            svc.run(
                PipelineOptions(file_path=str(doc), output_dir="out"),
                CollectingProgressReporter(),
                cancel_check=cancel_check,
            )

    mock_rel.extract.assert_not_called()
