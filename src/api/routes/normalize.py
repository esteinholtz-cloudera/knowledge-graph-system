"""Predicate normalization REST routes."""
from flask import Blueprint, current_app, jsonify, request

from src.services.normalize import NormalizeService

normalize_bp = Blueprint("normalize", __name__)


def _svc() -> NormalizeService:
    return NormalizeService(current_app.extensions["project_root"])


def _paths_from_request():
    kg_dir = request.args.get("kg_dir", "data/knowledge_graphs")
    ontology_file = request.args.get("ontology_file", "data/ontology/ontology.ttl")
    map_file = request.args.get("map_file", "data/predicate_map.yaml")
    return kg_dir, ontology_file, map_file


@normalize_bp.route("/normalize/map", methods=["GET"])
def get_map():
    _, _, map_file = _paths_from_request()
    return jsonify(_svc().get_map(map_file)), 200


@normalize_bp.route("/normalize/map/groups/<path:canonical>", methods=["PATCH"])
def update_group(canonical):
    body = request.get_json(silent=True) or {}
    _, _, map_file = _paths_from_request()
    try:
        updated = _svc().update_group(canonical, body, map_file=map_file)
    except FileNotFoundError as e:
        return jsonify({"error": {"code": "not_found", "message": str(e)}}), 404
    except KeyError as e:
        return jsonify({"error": {"code": "not_found", "message": str(e)}}), 404
    return jsonify(updated), 200


@normalize_bp.route("/normalize/scan", methods=["POST"])
def scan():
    body = request.get_json(silent=True) or {}
    kg_dir = body.get("kg_dir", "data/knowledge_graphs")
    map_file = body.get("map_file", "data/predicate_map.yaml")
    no_llm = bool(body.get("no_llm", False))
    result = _svc().scan(kg_dir, map_file, no_llm=no_llm)
    return jsonify({
        "map_path": result.map_path,
        "group_count": result.group_count,
        "review_count": result.review_count,
    }), 200


@normalize_bp.route("/normalize/apply", methods=["POST"])
def apply():
    body = request.get_json(silent=True) or {}
    kg_dir = body.get("kg_dir", "data/knowledge_graphs")
    ontology_file = body.get("ontology_file", "data/ontology/ontology.ttl")
    map_file = body.get("map_file", "data/predicate_map.yaml")
    dry_run = bool(body.get("dry_run", False))
    try:
        result = _svc().apply(kg_dir, ontology_file, map_file, dry_run=dry_run)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify({
        "files": result.files,
        "triples": result.triples,
        "dry_run": result.dry_run,
    }), 200
