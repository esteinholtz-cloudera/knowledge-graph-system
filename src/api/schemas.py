"""Pydantic request/response models for the HTTP API."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineRequest(BaseModel):
    file_path: str
    output_dir: str = "data/knowledge_graphs"
    max_chunks: Optional[int] = None
    with_graph: bool = False
    domain: str = "default"
    skip_precheck: bool = False


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PipelineJobCreated(BaseModel):
    job_id: str


class ConfigResponse(BaseModel):
    llm: Dict[str, Any]
    document: Dict[str, Any]
    entity_resolution: Dict[str, Any]
    pipeline: Dict[str, Any]
    domains: List[str]
