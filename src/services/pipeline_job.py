"""Background pipeline job execution."""
from pathlib import Path
from typing import Any, Dict

from src.extraction.entity_extractor import ExtractionError
from src.extraction.llm_errors import LLMError, job_error_message
from src.services.health import HealthService
from src.services.jobs import JobCancelled, JobStore
from src.services.models import PipelineOptions
from src.services.pipeline import PipelineService
from src.services.progress import JobProgressReporter, ProgressEvent, progress_event_to_dict


def execute_pipeline_job(job_id: str, params: Dict[str, Any], store: JobStore, project_root: Path) -> None:
    reporter = JobProgressReporter(job_id, store)
    cancel_check = lambda: store.is_cancelled(job_id)

    skip_precheck = bool(params.get("skip_precheck"))
    if not skip_precheck:
        pre = HealthService().check()
        reporter.emit(ProgressEvent(stage="precheck", message="precheck complete" if pre.ok else "precheck failed"))
        if not pre.ok:
            store.update_status(job_id, "failed", error="pre-flight checks failed")
            return

    file_path = params.get("file_path", "")
    options = PipelineOptions(
        file_path=file_path,
        output_dir=params.get("output_dir", "data/knowledge_graphs"),
        max_chunks=params.get("max_chunks"),
        with_graph=bool(params.get("with_graph", False)),
        domain=params.get("domain", "default"),
        skip_precheck=True,
    )

    try:
        result = PipelineService(project_root).run(
            options,
            reporter=reporter,
            cancel_check=cancel_check,
        )
        store.update_status(job_id, "succeeded", result=result.as_dict())
        reporter.emit(ProgressEvent(
            stage="done",
            payload={"result": result.as_dict()},
        ))
    except JobCancelled:
        raise
    except (ExtractionError, LLMError) as exc:
        message = job_error_message(exc)
        store.update_status(job_id, "failed", error=message)
        reporter.emit(ProgressEvent(stage="error", message=message))
