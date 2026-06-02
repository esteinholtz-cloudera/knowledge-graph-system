"""Legacy n8n HTTP routes (deprecated — use /api/v1)."""
from flask import Flask, jsonify, request

from src.n8n.nodes.extract_entities import extract_entities, extract_relationships
from src.n8n.nodes.process_document import process_document
from src.n8n.nodes.store_kg import store_knowledge_graph
from src.services.documents import DocumentService


def register_legacy_routes(app: Flask, project_root) -> None:
    @app.route("/process", methods=["POST"])
    def process():
        """Deprecated: use POST /api/v1/jobs/pipeline."""
        try:
            data = request.get_json() or {}
            file_path = data.get("file_path")
            if not file_path:
                return jsonify({"error": "file_path is required"}), 400
            chunk_size = data.get("chunk_size", 1000)
            overlap = data.get("overlap", 100)
            result = process_document(file_path, chunk_size=chunk_size, overlap=overlap)
            resp = jsonify(result)
            resp.headers["Deprecation"] = "true"
            resp.headers["Link"] = '</api/v1/jobs/pipeline>; rel="successor-version"'
            return resp, 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/extract/entities", methods=["POST"])
    def extract_entities_endpoint():
        try:
            data = request.get_json() or {}
            text = data.get("text")
            if not text:
                return jsonify({"error": "text is required"}), 400
            return jsonify(extract_entities(text)), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/extract/relationships", methods=["POST"])
    def extract_relationships_endpoint():
        try:
            data = request.get_json() or {}
            text = data.get("text")
            if not text:
                return jsonify({"error": "text is required"}), 400
            entities = data.get("entities")
            return jsonify(extract_relationships(text, entities)), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/store", methods=["POST"])
    def store():
        try:
            data = request.get_json() or {}
            document_id = data.get("document_id")
            triples = data.get("triples")
            if not document_id:
                return jsonify({"error": "document_id is required"}), 400
            if not triples:
                return jsonify({"error": "triples is required"}), 400
            result = store_knowledge_graph(
                document_id=document_id,
                triples=triples,
                document_metadata=data.get("document_metadata"),
                output_dir=data.get("output_dir", "data/knowledge_graphs"),
            )
            return jsonify(result), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/metadata", methods=["GET"])
    def list_documents():
        """Deprecated: use GET /api/v1/documents."""
        svc = DocumentService(project_root)
        docs = svc.list_documents()
        resp = jsonify({"documents": [d.get("id", d.get("filename")) for d in docs]})
        resp.headers["Deprecation"] = "true"
        return resp, 200

    @app.route("/metadata/<document_id>", methods=["GET"])
    def get_metadata(document_id):
        """Deprecated: use GET /api/v1/documents/<id>."""
        svc = DocumentService(project_root)
        doc = svc.get_document(document_id)
        if not doc:
            return jsonify({"error": "Document not found"}), 404
        resp = jsonify(doc)
        resp.headers["Deprecation"] = "true"
        return resp, 200
