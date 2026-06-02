"""API error handlers."""
from flask import Flask, jsonify


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(err):
        msg = getattr(err, "description", str(err))
        return jsonify({"error": {"code": "bad_request", "message": msg}}), 400

    @app.errorhandler(404)
    def not_found(err):
        msg = getattr(err, "description", "not found")
        return jsonify({"error": {"code": "not_found", "message": msg}}), 404

    @app.errorhandler(500)
    def server_error(err):
        msg = getattr(err, "description", "internal server error")
        return jsonify({"error": {"code": "internal_error", "message": msg}}), 500
