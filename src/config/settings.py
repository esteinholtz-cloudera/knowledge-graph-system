"""Load application settings from config.yaml."""
import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Literal, List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

_cli_overrides: Optional[dict] = None


LLMProvider = Literal["ollama", "lmstudio", "openai", "anthropic", "gemini", "subagent"]


class ModelOverrides(BaseModel):
    """Per-model overrides applied on top of the global LLM defaults.
    Only fields explicitly set in config are applied; None means "use default".
    Add new LLM-specific tuning knobs here as they are identified.

    TODO: LLM calibration
    The optimal values of chunk_size, overlap, section_size, and prompts vary
    per model (context window quality, instruction-following, tendency toward
    "lost in the middle"). Future work:
    - Automated calibration sweep: vary chunk_size / overlap / section_size across
      runs on a labelled document and use benchmark DB yield (entities/triples per
      token) to find the Pareto-optimal config per model.
    - Prompt calibration: A/B test entity and relationship extraction prompts
      (few-shot examples, CoT, output format variants) against a gold standard.
    - Coverage metric: fraction of source text covered by at least one entity
      mention — makes lost-in-the-middle degradation quantitative and comparable.
    See docs/Benchmark.md § Roadmap for tracking.
    """
    chunk_size: Optional[int] = None
    overlap: Optional[int] = None
    section_size: Optional[int] = None
    disable_thinking: Optional[bool] = None
    temperature: Optional[float] = None
    max_new_tokens: Optional[int] = None
    # Prompt format knobs — how strictly to enforce JSON-only output.
    # low    = current default ("Return ONLY a JSON array")
    # medium = adds explicit start/end markers
    # high   = adds inline example + hard constraint (for weaker instruction followers)
    format_strictness: Optional[Literal["low", "medium", "high"]] = None
    # Whether to prepend a few-shot example to the user prompt.
    # Helps smaller models that struggle with the output schema.
    use_few_shot: Optional[bool] = None


class DomainSettings(BaseModel):
    """Per-domain extraction configuration.
    Extra entity types and predicates are merged with the global defaults.
    """
    description: str = ""
    extra_entity_types: List[str] = Field(default_factory=list)
    extra_predicates: List[str] = Field(default_factory=list)

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
    model: Optional[str] = None  # null = auto-detect from /v1/models (first loaded model)
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout_seconds: int = 120
    temperature: float = 0.3
    max_new_tokens: int = 512
    disable_thinking: bool = False
    # --- subagent provider ---
    # Used only when provider == "subagent". The Cursor subagent becomes the LLM:
    # whatever model the subagent runs is the model used for generation.
    subagent_cli: str = "cursor-agent"  # CLI binary (on PATH or absolute path)
    subagent_mode: Literal["ask", "plan", "agent"] = "ask"  # ask = read-only Q&A
    subagent_trust: bool = True  # pass --trust for headless runs (no workspace prompt)
    # Default chunk settings — words per extraction call.
    # Override per model in model_settings below.
    chunk_size: int = 300
    overlap: int = 100
    # Number of consecutive chunks to group into one section for Pass 2b
    # cross-section relationship extraction. 0 or 1 disables the section pass.
    section_size: int = 5
    # Prompt format defaults (overridable per model)
    format_strictness: Literal["low", "medium", "high"] = "low"
    use_few_shot: bool = False
    # Per-model overrides keyed by the model name as reported by the provider.
    # Any field set here takes precedence over the defaults above for that model.
    model_settings: Dict[str, ModelOverrides] = Field(default_factory=dict)

    def for_model(self, model_name: str) -> "LLMSettings":
        """Return a copy of this config with model-specific overrides applied."""
        overrides = self.model_settings.get(model_name, ModelOverrides())
        data = self.model_dump(exclude={"model_settings"})
        for field in ModelOverrides.model_fields:
            value = getattr(overrides, field)
            if value is not None:
                data[field] = value
        return LLMSettings(**data)

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


class StorageSettings(BaseModel):
    knowledge_graphs_dir: str = "data/knowledge_graphs"
    metadata_file: str = "data/metadata.json"
    documents_dir: str = "data/documents"
    ontology_dir: str = "data/ontology"
    ontology_file: str = "data/ontology/ontology.ttl"


class PipelineSettings(BaseModel):
    # Max parallel LLM calls per chunk batch (entity + relationship passes).
    # Use 1 for local Ollama/LM Studio; increase for cloud APIs.
    max_concurrent_llm_calls: int = 1


class N8nSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5001
    debug: bool = False


class GuiSettings(BaseModel):
    port: int = 5173


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


class OntologySettings(BaseModel):
    # How to reach the Wikidata MCP server:
    #   subprocess — launch via uvx each time (no setup needed)
    #   http       — connect to a running HTTP server (future)
    #   disabled   — skip Wikidata lookups
    wikidata_mcp: Literal["subprocess", "http", "disabled"] = "subprocess"
    wikidata_mcp_url: Optional[str] = None  # used only when mode=http


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
    storage: StorageSettings = Field(default_factory=StorageSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    n8n: N8nSettings = Field(default_factory=N8nSettings)
    gui: GuiSettings = Field(default_factory=GuiSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    entity_resolution: EntityResolutionSettings = Field(default_factory=EntityResolutionSettings)
    ontology: OntologySettings = Field(default_factory=OntologySettings)
    visualization: VisualizationSettings = Field(default_factory=VisualizationSettings)
    domains: Dict[str, DomainSettings] = Field(default_factory=dict)

    def get_domain(self, name: str) -> DomainSettings:
        """Return domain settings by name, or empty defaults if unknown."""
        return self.domains.get(name, DomainSettings())


def _parse_override_value(raw: str) -> Any:
    """Parse a CLI override value into a Python object."""
    s = raw.strip()
    lower = s.lower()
    if lower in ("null", "none", "~"):
        return None
    if lower in ("true", "yes", "on"):
        return True
    if lower in ("false", "no", "off"):
        return False
    if s.startswith(("[", "{")):
        return json.loads(s)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    try:
        return int(s, 10)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _set_nested(target: dict, keys: list[str], value: Any) -> None:
    cursor = target
    for key in keys[:-1]:
        child = cursor.get(key)
        if not isinstance(child, dict):
            child = {}
            cursor[key] = child
        cursor = child
    cursor[keys[-1]] = value


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def overrides_from_cli(pairs: list[str]) -> dict:
    """Build a nested override dict from KEY=VALUE CLI strings (dotted keys)."""
    result: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid config override (expected KEY=VALUE): {pair!r}")
        key, _, raw_value = pair.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid config override (empty key): {pair!r}")
        _set_nested(result, key.split("."), _parse_override_value(raw_value))
    return result


def set_cli_overrides(overrides: dict) -> None:
    """Apply overrides to subsequent load_config() calls (typically from CLI -c/--set)."""
    global _cli_overrides
    _cli_overrides = overrides


def clear_cli_overrides() -> None:
    """Clear CLI overrides (for tests)."""
    global _cli_overrides
    _cli_overrides = None


def load_config(
    config_path: Optional[str] = None,
    overrides: Optional[dict] = None,
) -> AppSettings:
    """Load settings from YAML file, with optional CLI/programmatic overrides."""
    if config_path is None:
        root = Path(__file__).parent.parent.parent
        config_path = str(root / "config" / "config.yaml")
    path = Path(config_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        import logging
        logging.getLogger(__name__).warning("config.yaml not found at %s — using defaults", path)
        data = {}

    merged_overrides: dict = {}
    if _cli_overrides:
        merged_overrides = _deep_merge(merged_overrides, _cli_overrides)
    if overrides:
        merged_overrides = _deep_merge(merged_overrides, overrides)
    if merged_overrides:
        data = _deep_merge(data, merged_overrides)
    return AppSettings.model_validate(data)


class ConfigOverrideError(ValueError):
    """A -c/--set override was malformed or produced invalid configuration."""


def add_override_arg(parser: argparse.ArgumentParser) -> None:
    """Register the shared -c/--set config override flag on an argument parser."""
    parser.add_argument(
        "-c",
        "--set",
        action="append",
        dest="config_set",
        metavar="KEY=VALUE",
        default=[],
        help=(
            "Override config.yaml (dotted keys, e.g. llm.temperature=0.5). "
            "Repeatable; values: true/false/null, numbers, JSON, or strings."
        ),
    )


def apply_cli_overrides(config_set: List[str], config_path: Optional[str] = None) -> None:
    """Validate and install -c/--set overrides for subsequent load_config() calls.

    Raises ConfigOverrideError if a pair is malformed or yields invalid config.
    """
    clear_cli_overrides()
    if not config_set:
        return
    try:
        set_cli_overrides(overrides_from_cli(config_set))
        load_config(config_path)
    except ValidationError as e:
        raise ConfigOverrideError(f"Invalid config override: {e}") from e
    except ValueError as e:
        raise ConfigOverrideError(str(e)) from e
