"""Stable HTML anchor ids for entity spans in markup documents."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote


_PROPOSED_FROM_RE = re.compile(
    r"Proposed from:\s*([^;\n]+)",
    re.IGNORECASE,
)
_SOURCE_FILE_RE = re.compile(
    r"([\w.\-]+)\.(?:pdf|txt|md|markdown|docx|doc)\b",
    re.IGNORECASE,
)


def entity_markup_anchor(
    entity_uri: Optional[str] = None,
    entity_label: str = "",
    occurrence: int = 0,
) -> str:
    """Return a stable fragment id for an entity mention in markup HTML."""
    if entity_uri:
        local = unquote(entity_uri.rstrip("/").split("/")[-1])
        slug = local.replace("_", "-").replace(" ", "-")
    elif entity_label:
        slug = entity_label.strip().replace(" ", "-")
    else:
        slug = "unknown"

    slug = re.sub(r"[^\w\-]", "", slug, flags=re.ASCII).lower().strip("-")
    if not slug:
        slug = "entity"
    if slug[0].isdigit():
        slug = f"e-{slug}"

    if occurrence <= 0:
        return f"entity-{slug}"
    return f"entity-{slug}-{occurrence}"


def anchor_exists_in_html(html_text: str, anchor: str) -> bool:
    if not anchor:
        return False
    pattern = rf'\bid=["\']{re.escape(anchor)}["\']'
    return bool(re.search(pattern, html_text))


def document_id_from_proposal_text(*texts: Optional[str]) -> Optional[str]:
    """Extract document stem from proposal comment / proposed_by fields."""
    for raw in texts:
        if not raw:
            continue
        text = raw.strip()
        match = _PROPOSED_FROM_RE.search(text)
        if match:
            text = match.group(1).strip()
        file_match = _SOURCE_FILE_RE.search(text)
        if file_match:
            return Path(file_match.group(0)).stem
    return None


def document_id_from_source_ttl(source_ttl: str, project_root: Path) -> Optional[str]:
    if not source_ttl:
        return None
    path = Path(source_ttl)
    if not path.is_absolute():
        path = project_root / source_ttl
    if path.suffix == ".ttl" and path.exists():
        return path.stem
    return None


def source_document_for_entity(entity_uri: str, project_root: Path) -> Optional[str]:
    """Find document stem from doc:sourceDocument in KG TTL files."""
    if not entity_uri:
        return None

    from rdflib import Graph, URIRef

    from src.storage.rdf_utils import DOC

    kg_dir = project_root / "data" / "knowledge_graphs"
    if not kg_dir.is_dir():
        return None

    entity = URIRef(entity_uri)
    for ttl_path in sorted(kg_dir.glob("*.ttl")):
        graph = Graph()
        try:
            graph.parse(str(ttl_path), format="turtle")
        except Exception:
            continue
        for _, _, doc in graph.triples((entity, DOC.sourceDocument, None)):
            return _document_stem_from_doc_uri(str(doc))
    return None


def source_document_for_entity_label(entity_label: str, project_root: Path) -> Optional[str]:
    """Resolve document stem by entity label when only the name is known."""
    label = (entity_label or "").strip()
    if not label:
        return None

    from rdflib import Graph

    from src.storage.rdf_utils import DOC, create_entity_uri

    kg_dir = project_root / "data" / "knowledge_graphs"
    if not kg_dir.is_dir():
        return None

    entity = create_entity_uri(label)
    for ttl_path in sorted(kg_dir.glob("*.ttl")):
        graph = Graph()
        try:
            graph.parse(str(ttl_path), format="turtle")
        except Exception:
            continue
        for _, _, doc in graph.triples((entity, DOC.sourceDocument, None)):
            return _document_stem_from_doc_uri(str(doc))
    return None


def entity_uri_in_markup(html_text: str, entity_uri: str) -> bool:
    if not entity_uri:
        return False
    escaped = re.escape(entity_uri)
    return bool(re.search(rf'href=["\']{escaped}["\']', html_text))


def sample_entity_for_class(
    document_id: str,
    class_uri: str,
    project_root: Path,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (entity_uri, entity_label) for one entity typed with class_uri in a KG."""
    if not document_id or not class_uri:
        return None, None

    from rdflib import Graph, URIRef
    from rdflib.namespace import RDF

    from src.storage.rdf_utils import KG

    ttl_path = project_root / "data" / "knowledge_graphs" / f"{document_id}.ttl"
    if not ttl_path.is_file():
        return None, None

    graph = Graph()
    try:
        graph.parse(str(ttl_path), format="turtle")
    except Exception:
        return None, None

    class_ref = URIRef(class_uri)
    for entity in graph.subjects(RDF.type, class_ref):
        entity_str = str(entity)
        if not entity_str.startswith(str(KG)):
            continue
        local = unquote(entity_str.replace(str(KG), "")).replace("_", " ")
        return entity_str, local
    return None, None


def _document_stem_from_doc_uri(doc_str: str) -> str:
    from src.storage.rdf_utils import DOC

    if doc_str.startswith(str(DOC)):
        return doc_str.replace(str(DOC), "").strip("/").split("/")[-1]
    return Path(doc_str).stem
