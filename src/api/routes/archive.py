"""Archive REST routes."""
from flask import Blueprint, current_app, jsonify, request

from src.services.archive import ArchiveService

archive_bp = Blueprint("archive", __name__)


@archive_bp.route("/archive", methods=["POST"])
def create_archive():
    body = request.get_json(silent=True) or {}
    svc = ArchiveService(current_app.extensions["project_root"])
    try:
        result = svc.create(
            name=body.get("name"),
            llmnamed=bool(body.get("llmnamed", False)),
        )
    except FileExistsError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify({
        "archive_path": result.archive_path,
        "paths_updated": result.paths_updated,
        "ttl_files_updated": result.ttl_files_updated,
    }), 200
