"""Tests for progress reporters."""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.progress import CollectingProgressReporter, ProgressEvent


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
