"""Ontology proposal REST routes."""
from flask import Blueprint, current_app, jsonify, request

from src.services.ontology import OntologyService

ontology_bp = Blueprint("ontology", __name__)


def _svc() -> OntologyService:
    return OntologyService(current_app.extensions["project_root"])


@ontology_bp.route("/ontology/status", methods=["GET"])
def ontology_status():
    result = _svc().status()
    return jsonify({
        "summary": result.summary,
        "sub_taxonomy_proposals": result.sub_taxonomy_proposals,
        "pending": result.pending,
        "needs_typing": result.needs_typing,
    }), 200


@ontology_bp.route("/ontology/sub-taxonomy", methods=["GET"])
def list_sub_taxonomy():
    proposals = _svc().list_sub_taxonomy()
    return jsonify({"sub_taxonomy_proposals": proposals, "count": len(proposals)}), 200


@ontology_bp.route("/ontology/sub-taxonomy/<proposal_id>", methods=["GET"])
def get_sub_taxonomy(proposal_id):
    proposal = _svc().get_sub_taxonomy(proposal_id)
    if not proposal:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    return jsonify(proposal), 200


@ontology_bp.route("/ontology/sub-taxonomy/<proposal_id>", methods=["PATCH"])
def patch_sub_taxonomy(proposal_id):
    body = request.get_json(silent=True) or {}
    try:
        updated = _svc().update_sub_taxonomy(proposal_id, body)
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    except ValueError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify(updated), 200


@ontology_bp.route("/ontology/sub-taxonomy/<proposal_id>/approve", methods=["POST"])
def sub_taxonomy_approve(proposal_id):
    body = request.get_json(silent=True) or {}
    action = body.get("action", "approve")
    chain = body.get("chain")
    try:
        result = _svc().sub_taxonomy_approval(proposal_id, action, chain=chain)
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    except ValueError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify(result), 200


@ontology_bp.route("/ontology/proposals", methods=["GET"])
def list_proposals():
    filter_name = request.args.get("filter")
    proposals = _svc().list_proposals(filter_name=filter_name)
    return jsonify({"proposals": proposals, "count": len(proposals)}), 200


@ontology_bp.route("/ontology/proposals/<path:proposal_uri>", methods=["GET"])
def get_proposal(proposal_uri):
    proposal = _svc().get_proposal(proposal_uri)
    if not proposal:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    return jsonify(proposal), 200


@ontology_bp.route("/ontology/proposals/<path:proposal_uri>", methods=["PATCH"])
def update_proposal(proposal_uri):
    body = request.get_json(silent=True) or {}
    try:
        updated = _svc().update_proposal(proposal_uri, body)
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    except ValueError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify(updated), 200


@ontology_bp.route("/ontology/proposals/<path:proposal_uri>/wikidata-search", methods=["POST"])
def wikidata_search(proposal_uri):
    body = request.get_json(silent=True) or {}
    try:
        result = _svc().search_wikidata(proposal_uri, search_term=body.get("search_term"))
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    return jsonify(result), 200


@ontology_bp.route("/ontology/proposals/<path:proposal_uri>/wikidata-select", methods=["POST"])
def wikidata_select(proposal_uri):
    body = request.get_json(silent=True) or {}
    qid = body.get("qid")
    if not qid:
        return jsonify({"error": {"code": "bad_request", "message": "qid is required"}}), 400
    try:
        result = _svc().select_wikidata_entity(proposal_uri, qid)
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    return jsonify(result), 200


@ontology_bp.route("/ontology/proposals/<path:proposal_uri>/wikidata-parent", methods=["POST"])
def wikidata_parent(proposal_uri):
    body = request.get_json(silent=True) or {}
    qid = body.get("qid")
    if not qid:
        return jsonify({"error": {"code": "bad_request", "message": "qid is required"}}), 400
    try:
        result = _svc().approve_wikidata_parent(
            proposal_uri,
            qid,
            parent_label=body.get("label"),
        )
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    except ValueError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify(result), 200


@ontology_bp.route("/ontology/proposals/<path:proposal_uri>/suggest-placement", methods=["POST"])
def suggest_placement(proposal_uri):
    body = request.get_json(silent=True) or {}
    try:
        result = _svc().suggest_placement(
            proposal_uri,
            search_term=body.get("search_term"),
        )
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    return jsonify(result), 200


@ontology_bp.route("/ontology/wikidata-superclasses", methods=["POST"])
def wikidata_superclasses_route():
    body = request.get_json(silent=True) or {}
    qid = body.get("qid")
    if not qid:
        return jsonify({"error": {"code": "bad_request", "message": "qid is required"}}), 400
    result = _svc().get_wikidata_superclasses(qid)
    return jsonify(result), 200


@ontology_bp.route("/ontology/proposals/<path:proposal_uri>/approve-chain", methods=["POST"])
def approve_chain_route(proposal_uri):
    """Deprecated — delegates to sub-taxonomy approval."""
    body = request.get_json(silent=True) or {}
    chain = body.get("chain", [])
    if len(chain) < 2:
        return jsonify({"error": {"code": "bad_request", "message": "chain needs ≥2 nodes"}}), 400
    try:
        result = _svc().approve_chain(proposal_uri, chain)
    except KeyError:
        return jsonify({"error": {"code": "not_found", "message": "proposal not found"}}), 404
    except ValueError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify(result), 200


@ontology_bp.route("/ontology/approve", methods=["POST"])
def approve_ontology():
    result = _svc().approve_all()
    return jsonify({"approved_count": result.approved_count}), 200


@ontology_bp.route("/ontology/visualize", methods=["POST"])
def visualize_ontology():
    path = _svc().visualize()
    if not path:
        return jsonify({"error": {"code": "not_found", "message": "ontology.ttl not found"}}), 404
    return jsonify({"graph_path": path}), 200
