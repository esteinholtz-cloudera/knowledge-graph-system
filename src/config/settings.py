"""Load application settings from config.yaml."""
import os
from pathlib import Path
from typing import Literal, Optional

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


class ExtractionSettings(BaseModel):
    entity_extraction: dict = Field(default_factory=lambda: {"enabled": True})
    relationship_extraction: dict = Field(default_factory=lambda: {"enabled": True})


class AppSettings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    document: DocumentSettings = Field(default_factory=DocumentSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    n8n: N8nSettings = Field(default_factory=N8nSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)


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
