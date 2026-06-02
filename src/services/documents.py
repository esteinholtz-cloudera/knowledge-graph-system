"""Document listing, metadata, upload, and artifact path resolution."""
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from werkzeug.datastructures import FileStorage

from src.storage.metadata_store import MetadataStore

ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".doc"}


class PathTraversalError(ValueError):
    pass


def resolve_under_project(project_root: Path, relative_path: str) -> Path:
    """Resolve a path and ensure it stays under project_root."""
    if not relative_path or not str(relative_path).strip():
        raise PathTraversalError("path is required")
    if ".." in Path(relative_path).parts:
        raise PathTraversalError("path traversal not allowed")
    resolved = (project_root / relative_path).resolve()
    root = project_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise PathTraversalError("path outside project root") from None
    return resolved


def resolve_data_path(project_root: Path, relative_path: str) -> Path:
    """Resolve a path under project_root/data/."""
    data_root = (project_root / "data").resolve()
    path = resolve_under_project(project_root, relative_path)
    try:
        path.relative_to(data_root)
    except ValueError:
        raise PathTraversalError("artifact path must be under data/") from None
    return path


class DocumentService:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        metadata_store: Optional[MetadataStore] = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._store = metadata_store or MetadataStore(
            str(self.project_root / "data" / "metadata.json"),
        )

    def list_documents(self) -> List[Dict[str, Any]]:
        ids = self._store.list_documents()
        out = []
        for doc_id in ids:
            meta = self._store.get_document(doc_id)
            if meta:
                out.append({"id": doc_id, **meta})
        return out

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        meta = self._store.get_document(document_id)
        if not meta:
            return None
        stem = document_id
        return {
            "id": document_id,
            **meta,
            "artifacts": {
                "kg": self.artifact_path(document_id, "kg"),
                "markup": self.artifact_path(document_id, "markup"),
                "graph": self.artifact_path(document_id, "graph"),
            },
        }

    def artifact_path(self, document_id: str, kind: str) -> Optional[str]:
        meta = self._store.get_document(document_id)
        if not meta:
            return None
        if kind == "kg":
            kg = meta.get("kg_path")
            if kg and Path(kg).exists():
                return kg
            candidate = self.project_root / "data" / "knowledge_graphs" / f"{document_id}.ttl"
            return str(candidate) if candidate.exists() else None
        stem = document_id
        if kind == "markup":
            path = self.project_root / "data" / "documents" / f"{stem}_markup.html"
        elif kind == "graph":
            path = self.project_root / "data" / "documents" / f"{stem}_graph.html"
        else:
            return None
        return str(path) if path.exists() else None

    def resolve_artifact_file(self, document_id: str, kind: str) -> Path:
        path_str = self.artifact_path(document_id, kind)
        if not path_str:
            raise FileNotFoundError(f"No {kind} artifact for document {document_id}")
        path = Path(path_str).resolve()
        data_root = (self.project_root / "data").resolve()
        try:
            path.relative_to(data_root)
        except ValueError:
            raise PathTraversalError("artifact path must be under data/") from None
        if not path.is_file():
            raise FileNotFoundError(f"No {kind} artifact for document {document_id}")
        return path

    def upload(self, file: FileStorage) -> Dict[str, str]:
        if not file or not file.filename:
            raise ValueError("file is required")
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(
                f"unsupported extension {ext}; allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
            )
        safe_name = Path(file.filename).name
        dest_dir = self.project_root / "data" / "documents"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name
        file.save(str(dest))
        rel = str(dest.relative_to(self.project_root))
        return {"file_path": rel, "filename": safe_name}

    def resolve_file_path(self, file_path: str) -> Path:
        return resolve_under_project(self.project_root, file_path)
