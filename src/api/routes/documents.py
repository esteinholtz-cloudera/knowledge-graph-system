"""Document and artifact routes."""
from flask import Blueprint, current_app, jsonify, request, send_file

from src.services.documents import DocumentService, PathTraversalError

documents_bp = Blueprint("documents", __name__)


def _project_root():
    return current_app.extensions["project_root"]


def _doc_service():
    return DocumentService(_project_root())


@documents_bp.route("/documents", methods=["GET"])
def list_documents():
    return jsonify({"documents": _doc_service().list_documents()}), 200


@documents_bp.route("/documents/<document_id>", methods=["GET"])
def get_document(document_id):
    doc = _doc_service().get_document(document_id)
    if not doc:
        return jsonify({"error": {"code": "not_found", "message": "document not found"}}), 404
    return jsonify(doc), 200


@documents_bp.route("/documents/upload", methods=["POST"])
def upload_document():
    if "file" not in request.files:
        return jsonify({"error": {"code": "bad_request", "message": "file is required"}}), 400
    try:
        result = _doc_service().upload(request.files["file"])
    except ValueError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify(result), 201


@documents_bp.route("/artifacts/<document_id>/kg", methods=["GET"])
def artifact_kg(document_id):
    return _send_artifact(document_id, "kg", "text/turtle")


@documents_bp.route("/artifacts/<document_id>/markup", methods=["GET"])
def artifact_markup(document_id):
    return _send_artifact(document_id, "markup", "text/html")


@documents_bp.route("/artifacts/<document_id>/graph", methods=["GET"])
def artifact_graph(document_id):
    return _send_artifact(document_id, "graph", "text/html")


def _send_artifact(document_id: str, kind: str, mimetype: str):
    try:
        path = _doc_service().resolve_artifact_file(document_id, kind)
    except FileNotFoundError:
        return jsonify({"error": {"code": "not_found", "message": f"{kind} artifact not found"}}), 404
    except PathTraversalError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return send_file(path, mimetype=mimetype)
