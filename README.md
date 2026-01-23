# Knowledge Graph System

A standalone system for generating and managing knowledge graphs from documents. Each knowledge graph is linked to a document and stored in Turtle (RDF) format. The system uses the existing RAG chatbot's LLM for extraction and integrates with n8n via custom nodes for agent-based orchestration.

## Features

- **Multi-format Document Processing**: Supports text, Markdown, PDF, and Word documents
- **Entity Extraction**: Extract entities from documents using LLM
- **Relationship Extraction**: Extract relationships between entities
- **Turtle Format Storage**: Store knowledge graphs in RDF Turtle format (one file per document)
- **n8n Integration**: HTTP API endpoints for n8n workflow orchestration
- **Metadata Tracking**: Track document-to-knowledge graph mappings

## Project Structure

```
knowledge-graph-system/
├── src/
│   ├── document/          # Document processing
│   ├── extraction/        # Entity and relationship extraction
│   ├── storage/           # Knowledge graph storage
│   └── n8n/              # n8n integration
├── config/                # Configuration files
├── data/                  # Data directories
│   ├── documents/         # Input documents
│   ├── knowledge_graphs/ # Generated Turtle files
│   └── metadata.json     # Document metadata
├── pyproject.toml         # Project dependencies (uv)
└── main.py               # CLI entry point
```

## Installation

1. Install dependencies using uv:
```bash
uv sync
```

Or if you prefer pip:
```bash
pip install -e .
```

2. Ensure the RAG chatbot project is accessible (for LLM integration):
   - The system will try to auto-detect the RAG project
   - Or specify the path in `config/config.yaml`

## Usage

### CLI Usage

Process a document and extract knowledge graph:
```bash
python main.py process /path/to/document.pdf
```

Start the n8n API server:
```bash
python main.py server --port 5000
```

### n8n API Endpoints

The server exposes the following endpoints:

- `GET /health` - Health check
- `POST /process` - Process a document
  ```json
  {
    "file_path": "/path/to/document",
    "chunk_size": 1000,
    "overlap": 100
  }
  ```

- `POST /extract/entities` - Extract entities from text
  ```json
  {
    "text": "text to extract entities from"
  }
  ```

- `POST /extract/relationships` - Extract relationships from text
  ```json
  {
    "text": "text to extract relationships from",
    "entities": ["entity1", "entity2"]
  }
  ```

- `POST /store` - Store knowledge graph
  ```json
  {
    "document_id": "unique_id",
    "triples": [
      {"subject": "...", "predicate": "...", "object": "..."}
    ],
    "document_metadata": {...}
  }
  ```

- `GET /metadata/<document_id>` - Get document metadata
- `GET /metadata` - List all documents

## Workflow

1. **Document Ingestion**: Process document and extract text
2. **Extraction**: Extract entities and relationships using LLM
3. **Storage**: Convert to RDF format and save as Turtle file
4. **Metadata**: Track document-KG mappings

## Configuration

Edit `config/config.yaml` to customize:
- LLM parameters
- Document chunking settings
- Storage paths
- n8n server settings

## Integration with RAG LLM

The system integrates with the existing RAG chatbot LLM located at:
`_CML_AMP_LLM_Chatbot_Augmented_with_Enterprise_Data/utils/model_llm_utils.py`

The system will auto-detect the RAG project, or you can specify the path in the configuration.

## Future Enhancements

- Ontology management (planned for future phase)
- Entity deduplication across documents
- Knowledge graph querying and visualization
- Additional document formats

## License

See LICENSE file for details.

