"""Sanitized configuration endpoint."""
from flask import Blueprint, jsonify

from src.api.schemas import ConfigResponse
from src.config.settings import load_config

config_bp = Blueprint("config", __name__)


@config_bp.route("/config", methods=["GET"])
def get_config():
    app = load_config()
    llm = app.llm
    resp = ConfigResponse(
        llm={
            "provider": llm.provider,
            "model": llm.model,
            "base_url": llm.resolved_base_url(),
            "api_key_env": llm.resolved_api_key_env(),
            "timeout_seconds": llm.timeout_seconds,
            "temperature": llm.temperature,
            "chunk_size": llm.chunk_size,
            "overlap": llm.overlap,
        },
        document={
            "chunk_size": llm.chunk_size,
            "overlap": llm.overlap,
        },
        entity_resolution={
            "enabled": app.entity_resolution.enabled,
            "strategies": list(app.entity_resolution.strategies),
            "embedding_threshold": app.entity_resolution.embedding_threshold,
        },
        pipeline={
            "max_concurrent_llm_calls": app.pipeline.max_concurrent_llm_calls,
        },
        domains=list(app.domains.keys()) or ["default"],
    )
    return jsonify(resp.model_dump()), 200
