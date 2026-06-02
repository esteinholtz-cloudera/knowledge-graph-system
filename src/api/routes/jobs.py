"""Pipeline job routes."""
from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from src.api.schemas import PipelineJobCreated, PipelineRequest
from src.api.sse import job_events_stream
from src.services.documents import DocumentService, PathTraversalError
from src.services.pipeline_job import execute_pipeline_job

jobs_bp = Blueprint("jobs", __name__)


def _job_store():
    return current_app.extensions["job_store"]


def _job_runner():
    return current_app.extensions["job_runner"]


def _project_root():
    return current_app.extensions["project_root"]


@jobs_bp.route("/jobs", methods=["GET"])
def list_jobs():
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)
    jobs = _job_store().list(status=status, limit=limit)
    return jsonify({"jobs": [j.to_dict() for j in jobs]}), 200


@jobs_bp.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    job = _job_store().get(job_id)
    if not job:
        return jsonify({"error": {"code": "not_found", "message": "job not found"}}), 404
    return jsonify(job.to_dict()), 200


@jobs_bp.route("/jobs/<job_id>/events", methods=["GET"])
def job_events(job_id):
    job = _job_store().get(job_id)
    if not job:
        return jsonify({"error": {"code": "not_found", "message": "job not found"}}), 404

    from flask import Response
    return Response(
        job_events_stream(_job_store(), job_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@jobs_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    if not _job_store().request_cancel(job_id):
        job = _job_store().get(job_id)
        if not job:
            return jsonify({"error": {"code": "not_found", "message": "job not found"}}), 404
        return jsonify({"error": {"code": "bad_request", "message": "job already finished"}}), 400
    return jsonify({"status": "cancel_requested"}), 200


@jobs_bp.route("/jobs/pipeline", methods=["POST"])
def start_pipeline():
    body = request.get_json(silent=True) or {}
    try:
        req = PipelineRequest.model_validate(body)
    except ValidationError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400

    try:
        path = DocumentService(_project_root()).resolve_file_path(req.file_path)
        if not path.is_file():
            return jsonify({
                "error": {"code": "bad_request", "message": f"file not found: {req.file_path}"},
            }), 400
    except PathTraversalError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400

    params = req.model_dump()
    job = _job_store().create("pipeline.process", params)
    _job_runner().submit(
        execute_pipeline_job,
        job.id,
        params,
        _job_store(),
        _project_root(),
    )
    return jsonify(PipelineJobCreated(job_id=job.id).model_dump()), 202
