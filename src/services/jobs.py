"""In-memory job store and background runner."""
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

from src.services.progress import ProgressEvent

MAX_EVENTS_PER_JOB = 500
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


class JobCancelled(Exception):
    """Raised when a pipeline job is cancelled between chunks."""


@dataclass
class Job:
    id: str
    type: str
    status: str
    created_at: datetime
    params: Dict[str, Any]
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cancel_requested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "params": self.params,
            "result": self.result,
            "error": self.error,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._events: Dict[str, Deque[ProgressEvent]] = {}
        self._lock = threading.Lock()

    def create(self, job_type: str, params: dict) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            type=job_type,
            status="queued",
            created_at=datetime.now(timezone.utc),
            params=dict(params),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._events[job_id] = deque(maxlen=MAX_EVENTS_PER_JOB)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, status: Optional[str] = None, limit: int = 50) -> List[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs[:limit]

    def update_status(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            if status == "running" and job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            if status in TERMINAL_STATUSES:
                job.finished_at = datetime.now(timezone.utc)
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status in TERMINAL_STATUSES:
                return False
            job.cancel_requested = True
            return True

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.cancel_requested)

    def append_event(self, job_id: str, event: ProgressEvent) -> None:
        with self._lock:
            if job_id not in self._events:
                return
            self._events[job_id].append(event)

    def get_events(self, job_id: str, since_index: int = 0) -> List[ProgressEvent]:
        with self._lock:
            events = self._events.get(job_id)
            if not events:
                return []
            return list(events)[since_index:]

    def event_count(self, job_id: str) -> int:
        with self._lock:
            events = self._events.get(job_id)
            return len(events) if events else 0


class JobRunner:
    def __init__(self, store: JobStore) -> None:
        self._store = store

    def submit(self, fn: Callable, job_id: str, *args, **kwargs) -> threading.Thread:
        def _run():
            self._store.update_status(job_id, "running")
            try:
                fn(job_id, *args, **kwargs)
            except JobCancelled:
                self._store.update_status(job_id, "cancelled")
            except Exception as exc:
                if self._store.get(job_id) and self._store.get(job_id).status != "cancelled":
                    from src.extraction.llm_errors import job_error_message
                    self._store.update_status(job_id, "failed", error=job_error_message(exc))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return thread
