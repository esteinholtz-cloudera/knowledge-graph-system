"""Health and precheck routes."""
from flask import Blueprint, jsonify

from src.services.health import HealthService

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def liveness():
    return jsonify({"status": "healthy"}), 200


@health_bp.route("/health/precheck", methods=["GET"])
def precheck():
    result = HealthService().check()
    return jsonify({"ok": result.ok, "checks": result.checks}), 200
