"""Tests for in-memory job store and runner."""
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.jobs import JobRunner, JobStore
from src.services.progress import ProgressEvent


def test_job_lifecycle_and_events():
    store = JobStore()
    job = store.create("pipeline.process", {"file_path": "data/documents/x.txt"})
    assert job.status == "queued"

    def work(job_id, *_args, **_kwargs):
        store.update_status(job_id, "running")
        store.append_event(job_id, ProgressEvent(stage="entities", message="chunk 1"))
        store.update_status(job_id, "succeeded", result={"document_id": "x"})

    runner = JobRunner(store)
    runner.submit(work, job.id)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        updated = store.get(job.id)
        if updated and updated.status == "succeeded":
            break
        time.sleep(0.05)

    final = store.get(job.id)
    assert final is not None
    assert final.status == "succeeded"
    assert final.result == {"document_id": "x"}
    events = store.get_events(job.id)
    assert len(events) == 1
    assert events[0].stage == "entities"
