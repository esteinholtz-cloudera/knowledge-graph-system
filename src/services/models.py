"""Shared dataclasses for service layer results."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PrecheckResult:
    ok: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PipelineOptions:
    file_path: str
    output_dir: str = "data/knowledge_graphs"
    max_chunks: Optional[int] = None
    with_graph: bool = False
    domain: str = "default"
    skip_precheck: bool = False


@dataclass
class ChunkPlan:
    document_id: str
    filename: str
    word_count: int
    chunks: List[str]
    llm_model: str


@dataclass
class EntityPassResult:
    unique_entities: Dict[str, Dict[str, Any]]
    entities_raw: int
    chunk_entity_counts: List[int]


@dataclass
class PipelineResult:
    document_id: str
    kg_path: str
    markup_path: str
    graph_path: Optional[str]
    entity_count: int
    triple_count: int
    proposals: List[Dict[str, Any]]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "kg_path": self.kg_path,
            "markup_path": self.markup_path,
            "graph_path": self.graph_path,
            "entity_count": self.entity_count,
            "triple_count": self.triple_count,
            "proposals": self.proposals,
        }


@dataclass
class TableResult:
    columns: List[str]
    rows: List[List[Any]]
    text: str = ""


@dataclass
class OntologyStatusResult:
    summary: Dict[str, int]
    sub_taxonomy_proposals: List[Dict[str, Any]]
    pending: List[Dict[str, Any]]
    needs_typing: List[Dict[str, Any]]


@dataclass
class ArchiveResult:
    archive_path: str
    paths_updated: int
    ttl_files_updated: int


@dataclass
class ApproveOntologyResult:
    approved_count: int


@dataclass
class NormalizeScanResult:
    map_path: str
    group_count: int
    review_count: int


@dataclass
class NormalizeApplyResult:
    files: int
    triples: int
    dry_run: bool


@dataclass
class GraphGenerationResult:
    output_path: Optional[str]
    stdout_lines: List[str] = field(default_factory=list)
    stderr: str = ""
