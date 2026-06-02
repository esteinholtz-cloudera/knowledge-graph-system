"""Flask application factory."""
from pathlib import Path

from flask import Flask, jsonify

from src.api.errors import register_error_handlers
from src.api.routes.archive import archive_bp
from src.api.routes.benchmark import benchmark_bp
from src.api.routes.config import config_bp
from src.api.routes.documents import documents_bp
from src.api.routes.health import health_bp
from src.api.routes.jobs import jobs_bp
from src.api.routes.normalize import normalize_bp
from src.api.routes.ontology import ontology_bp
from src.n8n.legacy import register_legacy_routes
from src.services.jobs import JobRunner, JobStore


def create_app(project_root: Path = None) -> Flask:
    root = project_root or Path(__file__).resolve().parents[2]
    app = Flask(__name__)
    app.extensions["project_root"] = root
    app.extensions["job_store"] = JobStore()
    app.extensions["job_runner"] = JobRunner(app.extensions["job_store"])

    register_error_handlers(app)

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        return response

    @app.route("/health", methods=["GET"])
    def root_health():
        return jsonify({"status": "healthy"}), 200

    app.register_blueprint(health_bp, url_prefix="/api/v1")
    app.register_blueprint(config_bp, url_prefix="/api/v1")
    app.register_blueprint(jobs_bp, url_prefix="/api/v1")
    app.register_blueprint(documents_bp, url_prefix="/api/v1")
    app.register_blueprint(ontology_bp, url_prefix="/api/v1")
    app.register_blueprint(normalize_bp, url_prefix="/api/v1")
    app.register_blueprint(benchmark_bp, url_prefix="/api/v1")
    app.register_blueprint(archive_bp, url_prefix="/api/v1")

    register_legacy_routes(app, root)

    return app
