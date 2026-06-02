"""Progress reporting protocol for pipeline and job API."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.jobs import JobStore


STAGES = (
    "precheck",
    "plan",
    "entities",
    "resolve",
    "relationships",
    "sections",
    "write",
    "done",
    "error",
)


@dataclass
class ProgressEvent:
    stage: str
    job_id: str = ""
    chunk: Optional[int] = None
    total_chunks: Optional[int] = None
    message: str = ""
    percent: Optional[float] = None
    payload: Optional[Dict[str, Any]] = field(default_factory=dict)


class ProgressReporter(Protocol):
    def emit(self, event: ProgressEvent) -> None:
        ...


class NullProgressReporter:
    def emit(self, event: ProgressEvent) -> None:
        pass


def progress_event_to_dict(event: ProgressEvent) -> Dict[str, Any]:
    data = asdict(event)
    if data.get("payload") is None:
        data["payload"] = {}
    return data


class JobProgressReporter:
    """Appends progress events to a job store for SSE clients."""

    def __init__(self, job_id: str, store: "JobStore") -> None:
        self._job_id = job_id
        self._store = store

    def emit(self, event: ProgressEvent) -> None:
        event.job_id = self._job_id
        self._store.append_event(self._job_id, event)


class CollectingProgressReporter:
    """Stores events for unit tests."""

    def __init__(self) -> None:
        self.events: List[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)


class CliProgressReporter:
    """Maps progress events to the same console output as the legacy CLI."""

    def emit(self, event: ProgressEvent) -> None:
        payload = event.payload or {}
        kind = payload.get("kind")

        if kind == "processing_start":
            print(f"Processing document: {payload.get('file_path', '')}")
            return
        if kind == "domain":
            line = f"Domain: {payload.get('domain', '')}"
            desc = payload.get("description")
            if desc:
                line += f" — {desc}"
            print(line)
            return
        if kind == "document_info":
            print(f"Document:   {payload.get('filename', '')}")
            print(f"Word count: {payload.get('word_count', '')}")
            chunks_msg = payload.get("chunks_message", "")
            if chunks_msg:
                print(chunks_msg)
            return
        if kind == "pass_banner":
            width = payload.get("width", 50)
            print(f"\n{'═' * width}")
            print(f"  {payload.get('title', '')}")
            for extra in payload.get("lines", []):
                print(f"  {extra}")
            print(f"{'═' * width}")
            return
        if kind == "chunk_header":
            width = payload.get("width", 50)
            chunk_num = event.chunk or payload.get("chunk_num", 0)
            total = event.total_chunks or payload.get("total_chunks", 0)
            eta = payload.get("eta_str", "")
            print(f"\n{'─' * width}")
            print(f"  Chunk {chunk_num}/{total}{eta}")
            print(f"{'─' * width}")
            return
        if kind == "section_header":
            width = payload.get("width", 50)
            print(f"\n{'─' * width}")
            print(f"  {payload.get('title', '')}")
            print(f"{'─' * width}")
            return
        if kind == "extraction_error":
            width = payload.get("width", 50)
            print(f"\n{'═' * width}")
            print(f"  EXTRACTION ERROR — chunk {payload.get('chunk_num')}/{payload.get('total_chunks')}")
            print(f"{'═' * width}")
            print(payload.get("detail", ""))
            print("\nHints:")
            for hint in payload.get("hints", []):
                print(f"  • {hint}")
            return
        if kind == "proposals":
            proposals = payload.get("proposals", [])
            if not proposals:
                return
            print(f"\n   *** {len(proposals)} ontology addition(s) proposed for review ***")
            for p in proposals:
                sources = "; ".join(p["sources"]) if p.get("sources") else "(no source recorded)"
                print(f"       • {p['label']}  ←  {sources}")
            print(f"   Review: data/ontology/ontology_proposed.ttl")
            print(f"   Approve with: python main.py ontology approve")
            return
        if kind == "write_step":
            print(payload.get("line", ""))
            return
        if kind == "graph_generation":
            sub = payload.get("subkind")
            if sub == "skip":
                print(payload.get("line", ""))
            elif sub == "start":
                print(payload.get("line", "  Generating graph visualisation..."))
            elif sub == "stats":
                print(f"    {payload.get('line', '').strip()}")
            elif sub == "saved":
                print(f"  Graph HTML saved to: {payload.get('path', '')}")
            elif sub == "failed":
                print(f"  ✗ Graph generation failed:\n{payload.get('stderr', '').strip()}")
            return

        if event.message:
            print(event.message)


def format_eta(chunk_times: List[float], remaining_chunks: int) -> str:
    if not chunk_times or remaining_chunks <= 0:
        return ""
    avg = sum(chunk_times) / len(chunk_times)
    remaining = avg * remaining_chunks
    m, s = divmod(int(remaining), 60)
    if m:
        return f"  ETA ~{m}m{s:02d}s"
    return f"  ETA ~{s}s"
