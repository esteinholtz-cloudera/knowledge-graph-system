"""Benchmark metrics REST routes."""
from flask import Blueprint, jsonify, request

from src.services.benchmark import BenchmarkService

benchmark_bp = Blueprint("benchmark", __name__)
_svc = BenchmarkService()


@benchmark_bp.route("/benchmark/runs", methods=["GET"])
def benchmark_runs():
    return jsonify(_svc.as_json(_svc.get_view("runs"))), 200


@benchmark_bp.route("/benchmark/chunks", methods=["GET"])
def benchmark_chunks():
    return jsonify(_svc.as_json(_svc.get_view("chunks"))), 200


@benchmark_bp.route("/benchmark/llm", methods=["GET"])
def benchmark_llm():
    return jsonify(_svc.as_json(_svc.get_view("llm"))), 200


@benchmark_bp.route("/benchmark/query", methods=["POST"])
def benchmark_query():
    body = request.get_json(silent=True) or {}
    sql = body.get("sql", "")
    try:
        table = _svc.query(sql)
    except ValueError as e:
        return jsonify({"error": {"code": "bad_request", "message": str(e)}}), 400
    return jsonify(_svc.as_json(table)), 200


@benchmark_bp.route("/benchmark", methods=["DELETE"])
def benchmark_clear():
    _svc.clear()
    return jsonify({"status": "cleared"}), 200
