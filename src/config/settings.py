"""Load application settings from config.yaml."""
import os
from pathlib import Path
from typing import Dict, Literal, List, Optional

import yaml
from pydantic import BaseModel, Field


LLMProvider = Literal["ollama", "lmstudio", "openai", "anthropic", "gemini"]

DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "openai": "https://api.openai.com/v1",
}

DEFAULT_API_KEY_ENV = {
    "ollama": None,
    "lmstudio": None,
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class LLMSettings(BaseModel):
    provider: LLMProvider = "ollama"
    model: str = "llama3.2"
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout_seconds: int = 120
    temperature: float = 0.3
    max_new_tokens: int = 512
    # Set to true to prepend /no_think to system prompts.
    # Recommended for qwen3 and other thinking models to avoid token exhaustion.
    disable_thinking: bool = False

    def resolved_base_url(self) -> Optional[str]:
        if self.base_url:
            return self.base_url.rstrip("/")
        return DEFAULT_BASE_URLS.get(self.provider)  # None for anthropic/gemini

    def resolved_api_key_env(self) -> Optional[str]:
        if self.api_key_env is not None:
            return self.api_key_env or None
        return DEFAULT_API_KEY_ENV.get(self.provider)

    def get_api_key(self) -> Optional[str]:
        env_name = self.resolved_api_key_env()
        if not env_name:
            return None
        return os.environ.get(env_name)


class DocumentSettings(BaseModel):
    chunk_size: int = 1000
    overlap: int = 100


class StorageSettings(BaseModel):
    knowledge_graphs_dir: str = "data/knowledge_graphs"
    metadata_file: str = "data/metadata.json"
    documents_dir: str = "data/documents"
    ontology_dir: str = "data/ontology"
    ontology_file: str = "data/ontology/ontology.ttl"


class N8nSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False


class EntityResolutionSettings(BaseModel):
    enabled: bool = False
    # Strategies to apply in order. Options: rule_based, embedding, llm
    strategies: List[Literal["rule_based", "embedding", "llm"]] = ["rule_based"]
    # Embedding similarity threshold (0–1). Pairs above this are candidate matches.
    embedding_threshold: float = 0.92
    # Model for embeddings (OpenAI-compatible /v1/embeddings endpoint).
    # Defaults to the same base_url as the LLM provider.
    embedding_model: str = "text-embedding-nomic-embed-text-v1.5"
    # Whether to use the LLM to confirm ambiguous embedding matches before merging.
    llm_confirmation: bool = True
    # Canonical form preference when merging: "longer" | "title_case" | "first_seen"
    canonical_form: Literal["longer", "title_case", "first_seen"] = "title_case"
    # Custom abbreviation hints: {"LLM": "Large Language Model", ...}
    abbreviation_hints: Dict[str, str] = Field(default_factory=dict)


class ExtractionSettings(BaseModel):
    entity_extraction: dict = Field(default_factory=lambda: {"enabled": True})
    relationship_extraction: dict = Field(default_factory=lambda: {"enabled": True})


class VisualizationSettings(BaseModel):
    # Path to the ai-knowledge-graph project (for ttl_to_html.py graph generation).
    # null = auto-detect sibling directory ~/src/ai-knowledge-graph.
    ai_kg_path: Optional[str] = None

    def resolved_ai_kg_path(self) -> Optional[str]:
        if self.ai_kg_path:
            return self.ai_kg_path
        # Auto-detect common sibling locations
        from pathlib import Path
        candidates = [
            Path.home() / "src" / "ai-knowledge-graph",
            Path(__file__).parent.parent.parent.parent / "ai-knowledge-graph",
        ]
        for p in candidates:
            if (p / "ttl_to_html.py").exists():
                return str(p)
        return None


class AppSettings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    document: DocumentSettings = Field(default_factory=DocumentSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    n8n: N8nSettings = Field(default_factory=N8nSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    entity_resolution: EntityResolutionSettings = Field(default_factory=EntityResolutionSettings)
    visualization: VisualizationSettings = Field(default_factory=VisualizationSettings)


def load_config(config_path: Optional[str] = None) -> AppSettings:
    """Load settings from YAML file."""
    if config_path is None:
        root = Path(__file__).parent.parent.parent
        config_path = str(root / "config" / "config.yaml")
    path = Path(config_path)
    if not path.exists():
        import logging
        logging.getLogger(__name__).warning("config.yaml not found at %s — using defaults", path)
        return AppSettings()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return AppSettings.model_validate(data)
