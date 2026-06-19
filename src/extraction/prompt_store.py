"""Load and regenerate concrete extraction prompts from disk (per model + domain)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .prompt_layout import UserPromptLayout

if TYPE_CHECKING:
    from ..config.settings import DomainSettings, LLMSettings

FALLBACK_MODEL = "_default"

PROMPT_FILES = {
    "entity.system": "entity.system.txt",
    "entity.user.prefix": "entity.user.prefix.txt",
    "entity.user.suffix": "entity.user.suffix.txt",
    "relationship.system": "relationship.system.txt",
    "relationship.user.prefix": "relationship.user.prefix.txt",
    "relationship.user.suffix": "relationship.user.suffix.txt",
}


class PromptStore:
    """Read/write fully-resolved prompts under prompts/{model}/{domain}/."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.prompts_dir = project_root / "prompts"

    def instance_dir(self, model: str, domain: str) -> Path:
        return self.prompts_dir / model / domain

    def list_models(self) -> List[str]:
        if not self.prompts_dir.is_dir():
            return []
        return sorted(
            p.name for p in self.prompts_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def list_domains(self, model: str) -> List[str]:
        directory = self.prompts_dir / model
        if not directory.is_dir():
            return []
        return sorted(
            p.name for p in directory.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def list_files(self, model: str, domain: str) -> List[Path]:
        directory = self.instance_dir(model, domain)
        if not directory.is_dir():
            return []
        return sorted(directory.glob("*.txt"))

    def _resolve_instance_dir(self, model_name: str, domain_name: str) -> Optional[Path]:
        for model, domain in _resolution_candidates(model_name, domain_name):
            directory = self.instance_dir(model, domain)
            if (directory / PROMPT_FILES["entity.system"]).is_file():
                return directory
        return None

    def _read_text(self, directory: Path, key: str) -> Optional[str]:
        path = directory / PROMPT_FILES[key]
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return None

    def _load_bundle(
        self,
        directory: Path,
        *,
        task: str,
    ) -> Tuple[str, UserPromptLayout]:
        if task == "entity":
            system = self._read_text(directory, "entity.system")
            prefix = self._read_text(directory, "entity.user.prefix")
            suffix = self._read_text(directory, "entity.user.suffix")
        else:
            system = self._read_text(directory, "relationship.system")
            prefix = self._read_text(directory, "relationship.user.prefix")
            suffix = self._read_text(directory, "relationship.user.suffix")
        if system is None or prefix is None or suffix is None:
            raise FileNotFoundError(directory)
        return system, UserPromptLayout(prefix=prefix, suffix=suffix)

    def load_entity_prompts(
        self,
        *,
        model_name: str,
        domain_name: str,
        llm_cfg: "LLMSettings",
        domain: "DomainSettings",
    ) -> Tuple[str, UserPromptLayout]:
        from .prompt_builder import build_entity_prompt_bundle

        directory = self._resolve_instance_dir(model_name, domain_name)
        if directory is not None:
            return self._load_bundle(directory, task="entity")
        return build_entity_prompt_bundle(llm_cfg, domain)

    def load_relationship_prompts(
        self,
        *,
        model_name: str,
        domain_name: str,
        llm_cfg: "LLMSettings",
        domain: "DomainSettings",
    ) -> Tuple[str, UserPromptLayout]:
        from .prompt_builder import build_relationship_prompt_bundle

        directory = self._resolve_instance_dir(model_name, domain_name)
        if directory is not None:
            return self._load_bundle(directory, task="relationship")
        return build_relationship_prompt_bundle(llm_cfg, domain)

    def write_instance(
        self,
        model: str,
        domain: str,
        llm_cfg: "LLMSettings",
        domain_cfg: "DomainSettings",
        *,
        force: bool = False,
    ) -> List[Path]:
        from .prompt_builder import (
            build_entity_prompt_bundle,
            build_relationship_prompt_bundle,
        )

        directory = self.instance_dir(model, domain)
        directory.mkdir(parents=True, exist_ok=True)

        entity_system, entity_user = build_entity_prompt_bundle(llm_cfg, domain_cfg)
        rel_system, rel_user = build_relationship_prompt_bundle(llm_cfg, domain_cfg)

        payloads = {
            "entity.system": entity_system,
            "entity.user.prefix": entity_user.prefix,
            "entity.user.suffix": entity_user.suffix,
            "relationship.system": rel_system,
            "relationship.user.prefix": rel_user.prefix,
            "relationship.user.suffix": rel_user.suffix,
        }

        written: List[Path] = []
        for key, content in payloads.items():
            path = directory / PROMPT_FILES[key]
            if path.exists() and not force:
                continue
            path.write_text(content, encoding="utf-8")
            written.append(path)
        return written

    def regenerate(
        self,
        models: List[str],
        domains: List[str],
        llm_settings: "LLMSettings",
        domain_settings: Dict[str, "DomainSettings"],
        *,
        force: bool = False,
    ) -> Dict[str, Dict[str, List[Path]]]:
        from ..config.settings import DomainSettings

        results: Dict[str, Dict[str, List[Path]]] = {}
        for model in models:
            llm_cfg = llm_settings if model == FALLBACK_MODEL else llm_settings.for_model(model)
            results[model] = {}
            for domain in domains:
                domain_cfg = domain_settings.get(domain, DomainSettings())
                results[model][domain] = self.write_instance(
                    model, domain, llm_cfg, domain_cfg, force=force,
                )
        return results


def _resolution_candidates(model_name: str, domain_name: str) -> List[Tuple[str, str]]:
    return [
        (model_name, domain_name),
        (model_name, "default"),
        (FALLBACK_MODEL, domain_name),
        (FALLBACK_MODEL, "default"),
    ]
