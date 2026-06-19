"""Server-Sent Events helpers."""
import json
import time
from typing import Generator

from src.services.jobs import TERMINAL_STATUSES, JobStore
from src.services.progress import progress_event_to_dict


def job_events_stream(
    store: JobStore,
    job_id: str,
    poll_interval: float = 0.5,
) -> Generator[str, None, None]:
    since = 0
    while True:
        events = store.get_events(job_id, since_index=since)
        for event in events:
            payload = progress_event_to_dict(event)
            yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
            since += 1

        job = store.get(job_id)
        if not job:
            yield f"event: job_failed\ndata: {json.dumps({'message': 'job not found'})}\n\n"
            break

        if job.status in TERMINAL_STATUSES:
            if job.status == "succeeded" and job.result:
                yield f"event: done\ndata: {json.dumps(job.result)}\n\n"
            elif job.status == "failed":
                yield f"event: job_failed\ndata: {json.dumps({'message': job.error or 'failed'})}\n\n"
            elif job.status == "cancelled":
                yield f"event: cancelled\ndata: {json.dumps({'message': 'cancelled'})}\n\n"
            break

        time.sleep(poll_interval)
