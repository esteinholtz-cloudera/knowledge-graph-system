"""Tests for progress reporters."""
import sys
from io import StringIO
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.progress import CliProgressReporter, CollectingProgressReporter, ProgressEvent


def test_collecting_reporter_stages_for_two_chunk_run():
    """Simulate pipeline progress for a 2-chunk run without LLM."""
    rep = CollectingProgressReporter()
    total = 2

    rep.emit(ProgressEvent(stage="plan", payload={"kind": "processing_start", "file_path": "doc.txt"}))
    rep.emit(ProgressEvent(
        stage="entities",
        payload={"kind": "pass_banner", "title": "Pass 1 of 2 — Entity extraction", "lines": []},
    ))
    for chunk_num in (1, 2):
        rep.emit(ProgressEvent(
            stage="entities",
            chunk=chunk_num,
            total_chunks=total,
            payload={"kind": "chunk_header", "eta_str": ""},
        ))
        rep.emit(ProgressEvent(
            stage="entities",
            chunk=chunk_num,
            total_chunks=total,
            message=f"  ✓ Entities: 3  (1.0s)",
        ))
    rep.emit(ProgressEvent(stage="relationships", payload={"kind": "pass_banner", "title": "Pass 2", "lines": []}))
    for chunk_num in (1, 2):
        rep.emit(ProgressEvent(
            stage="relationships",
            chunk=chunk_num,
            total_chunks=total,
            payload={"kind": "chunk_header"},
        ))
    rep.emit(ProgressEvent(stage="write", payload={"kind": "write_step", "line": "1. TTL..."}))
    rep.emit(ProgressEvent(stage="done"))

    stages = [e.stage for e in rep.events]
    assert "plan" in stages
    assert stages.count("entities") >= 5
    assert "relationships" in stages
    assert "write" in stages
    assert stages[-1] == "done"

    entity_chunks = [
        e.chunk for e in rep.events
        if e.stage == "entities" and e.chunk is not None and e.message
    ]
    assert entity_chunks == [1, 2]


def test_cli_reporter_emits_expected_output_for_two_chunk_run(capsys):
    """CliProgressReporter maps ProgressEvents to the expected console patterns."""
    rep = CliProgressReporter()

    rep.emit(ProgressEvent(stage="plan", payload={"kind": "processing_start", "file_path": "doc.txt"}))
    rep.emit(ProgressEvent(
        stage="plan",
        payload={"kind": "document_info", "filename": "doc.txt", "word_count": 500, "chunks_message": "Split into 2 chunks"},
    ))
    rep.emit(ProgressEvent(
        stage="entities",
        payload={"kind": "pass_banner", "title": "Pass 1 of 2 — Entity extraction", "lines": ["(2 chunks)"]},
    ))
    for chunk_num in (1, 2):
        rep.emit(ProgressEvent(
            stage="entities", chunk=chunk_num, total_chunks=2,
            payload={"kind": "chunk_header", "eta_str": ""},
        ))
        rep.emit(ProgressEvent(stage="entities", chunk=chunk_num, total_chunks=2, message=f"  ✓ Entities: 3  (1.0s)"))
    rep.emit(ProgressEvent(stage="done", message="Processing complete"))

    captured = capsys.readouterr().out
    assert "Processing document: doc.txt" in captured
    assert "Pass 1 of 2 — Entity extraction" in captured
    assert "Chunk 1/2" in captured
    assert "Chunk 2/2" in captured
    assert "Processing complete" in captured
