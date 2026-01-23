"""HTTP server for n8n integration."""
from flask import Flask, request, jsonify
from pathlib import Path
import sys
import os

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.n8n.nodes.process_document import process_document
from src.n8n.nodes.extract_entities import extract_entities, extract_relationships
from src.n8n.nodes.store_kg import store_knowledge_graph
from src.storage.metadata_store import MetadataStore

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'}), 200


@app.route('/process', methods=['POST'])
def process():
    """
    Process a document.
    
    Request body:
    {
        "file_path": "/path/to/document",
        "chunk_size": 1000,
        "overlap": 100
    }
    """
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        
        if not file_path:
            return jsonify({'error': 'file_path is required'}), 400
        
        chunk_size = data.get('chunk_size', 1000)
        overlap = data.get('overlap', 100)
        
        result = process_document(file_path, chunk_size=chunk_size, overlap=overlap)
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/extract/entities', methods=['POST'])
def extract_entities_endpoint():
    """
    Extract entities from text.
    
    Request body:
    {
        "text": "text to extract entities from"
    }
    """
    try:
        data = request.get_json()
        text = data.get('text')
        
        if not text:
            return jsonify({'error': 'text is required'}), 400
        
        result = extract_entities(text)
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/extract/relationships', methods=['POST'])
def extract_relationships_endpoint():
    """
    Extract relationships from text.
    
    Request body:
    {
        "text": "text to extract relationships from",
        "entities": ["entity1", "entity2"]  # optional
    }
    """
    try:
        data = request.get_json()
        text = data.get('text')
        
        if not text:
            return jsonify({'error': 'text is required'}), 400
        
        entities = data.get('entities')
        
        result = extract_relationships(text, entities)
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/store', methods=['POST'])
def store():
    """
    Store knowledge graph.
    
    Request body:
    {
        "document_id": "unique_id",
        "triples": [
            {"subject": "...", "predicate": "...", "object": "..."}
        ],
        "document_metadata": {...}  # optional
    }
    """
    try:
        data = request.get_json()
        document_id = data.get('document_id')
        triples = data.get('triples')
        
        if not document_id:
            return jsonify({'error': 'document_id is required'}), 400
        if not triples:
            return jsonify({'error': 'triples is required'}), 400
        
        document_metadata = data.get('document_metadata')
        output_dir = data.get('output_dir', 'data/knowledge_graphs')
        
        result = store_knowledge_graph(
            document_id=document_id,
            triples=triples,
            document_metadata=document_metadata,
            output_dir=output_dir
        )
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/metadata/<document_id>', methods=['GET'])
def get_metadata(document_id):
    """Get document metadata."""
    try:
        store = MetadataStore()
        metadata = store.get_document(document_id)
        
        if metadata:
            return jsonify(metadata), 200
        else:
            return jsonify({'error': 'Document not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/metadata', methods=['GET'])
def list_documents():
    """List all documents."""
    try:
        store = MetadataStore()
        document_ids = store.list_documents()
        
        return jsonify({'documents': document_ids}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='n8n Knowledge Graph API Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    app.run(host=args.host, port=args.port, debug=args.debug)

