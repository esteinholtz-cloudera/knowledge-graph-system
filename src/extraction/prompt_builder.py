"""
Build extraction prompts from LLM settings and domain configuration.

Used to regenerate concrete prompt instance files under prompts/{model}/{domain}/.
At extraction time the pipeline reads those files directly — no runtime templating.

Regenerate with:
  python main.py prompts regenerate --model qwen3-30b-a3b-instruct-2507-mlx --domain technical
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

from .prompt_layout import UserPromptLayout

if TYPE_CHECKING:
    from ..config.settings import DomainSettings, LLMSettings

# Base entity types always included.
BASE_ENTITY_TYPES = [
    "Person", "Organization", "Location", "Technology",
    "Concept", "Product", "Event", "Date", "Other",
]

# Base relationship predicates always included.
BASE_PREDICATES = [
    "requires", "supports", "hasVersion", "isPartOf", "configures", "uses",
    "enables", "isCompatibleWith", "hasProperty", "replaces", "upgradesTo",
    "instanceOf", "locatedIn", "worksFor", "produces", "dependsOn",
    "manages", "references",
]

_FORMAT_SUFFIX = {
    "low": "",
    "medium": " Start your response with [ and end with ].",
    "high": ' Start with [ and end with ]. Do NOT write any text outside the JSON.',
}

_EE_FEW_SHOT = '''Example input: "Marie Curie discovered radium in Paris in 1898."
Example output:
[
  {"entity": "Marie Curie", "type": "Person", "context": "scientist who discovered radium"},
  {"entity": "radium", "type": "Technology", "context": "element discovered by Marie Curie"},
  {"entity": "Paris", "type": "Location", "context": "city where discovery occurred"},
  {"entity": "1898", "type": "Date", "context": "year of discovery"}
]

'''

_RE_FEW_SHOT = '''Example input: "Marie Curie discovered radium in Paris."
Entities: Marie Curie, radium, Paris
Example output:
[
  {"subject": "Marie Curie", "predicate": "produces", "object": "radium"},
  {"subject": "Marie Curie", "predicate": "locatedIn", "object": "Paris"}
]

'''

_ENTITY_USER_SUFFIX = "\n\nJSON array (no preamble):"
_RELATIONSHIP_USER_SUFFIX = "\n\nJSON array of triples (no preamble):"


def _merged_types(domain: "DomainSettings") -> List[str]:
    seen = set(BASE_ENTITY_TYPES)
    types = list(BASE_ENTITY_TYPES)
    for t in domain.extra_entity_types:
        if t not in seen:
            types.append(t)
            seen.add(t)
    return types


def _merged_predicates(domain: "DomainSettings") -> List[str]:
    seen = set(BASE_PREDICATES)
    predicates = list(BASE_PREDICATES)
    for p in domain.extra_predicates:
        if p not in seen:
            predicates.append(p)
            seen.add(p)
    return predicates


def _format_suffix(llm_cfg: "LLMSettings") -> str:
    return _FORMAT_SUFFIX.get(llm_cfg.format_strictness, "")


def _entity_few_shot(llm_cfg: "LLMSettings") -> str:
    return _EE_FEW_SHOT if llm_cfg.use_few_shot else ""


def _relationship_few_shot(llm_cfg: "LLMSettings") -> str:
    return _RE_FEW_SHOT if llm_cfg.use_few_shot else ""


def _domain_hint(domain: "DomainSettings") -> str:
    return f"\nDomain context: {domain.description}." if domain.description else ""


def _build_entity_system(llm_cfg: "LLMSettings", domain: "DomainSettings") -> str:
    type_list = " | ".join(_merged_types(domain))
    return (
        f"You are an expert at extracting named entities from text.{_domain_hint(domain)}\n\n"
        f"Extract all meaningful entities.\n\n"
        f"Return ONLY a JSON array — no explanation, no markdown, no preamble."
        f"{_format_suffix(llm_cfg)} Each element must have:\n"
        f'- "entity": the entity name exactly as it appears in the text\n'
        f'- "type": one of {type_list}\n'
        f'- "context": one short phrase describing the entity\'s role in the text'
    )


def _build_relationship_system(llm_cfg: "LLMSettings", domain: "DomainSettings") -> str:
    pred_list = ", ".join(_merged_predicates(domain))
    return (
        f"You are an expert at extracting relationships between entities from text."
        f"{_domain_hint(domain)}\n\n"
        f"Return ONLY a JSON array of triples — no explanation, no markdown, no preamble."
        f"{_format_suffix(llm_cfg)} Each element must have:\n"
        f'- "subject": source entity name\n'
        f'- "predicate": use the closest canonical verb from this list '
        f"(do NOT invent new predicates unless none fit):\n"
        f"    {pred_list}\n"
        f'- "object": target entity name\n\n'
        f"Optional fields — add ONLY when clearly present in the text:\n"
        f'- "scope": the specific component, context, or condition this relationship applies to\n'
        f'- "strength": "mandatory" | "recommended" | "conditional"\n\n'
        f'Example with scope: {{"subject": "ZDU", "predicate": "requires", '
        f'"object": "High Availability", "scope": "Kafka", "strength": "mandatory"}}\n\n'
        f"Only include relationships explicitly stated or strongly implied."
    )


def build_entity_user_layout(llm_cfg: "LLMSettings", domain: "DomainSettings") -> UserPromptLayout:
    del domain  # reserved for domain-specific user layouts later
    return UserPromptLayout(
        prefix=f"{_entity_few_shot(llm_cfg)}Text:\n",
        suffix=_ENTITY_USER_SUFFIX,
    )


def build_relationship_user_layout(llm_cfg: "LLMSettings", domain: "DomainSettings") -> UserPromptLayout:
    del domain
    return UserPromptLayout(
        prefix=f"{_relationship_few_shot(llm_cfg)}Text:\n",
        suffix=_RELATIONSHIP_USER_SUFFIX,
    )


def build_entity_prompt_bundle(
    llm_cfg: "LLMSettings",
    domain: "DomainSettings",
) -> Tuple[str, UserPromptLayout]:
    return _build_entity_system(llm_cfg, domain), build_entity_user_layout(llm_cfg, domain)


def build_relationship_prompt_bundle(
    llm_cfg: "LLMSettings",
    domain: "DomainSettings",
) -> Tuple[str, UserPromptLayout]:
    return _build_relationship_system(llm_cfg, domain), build_relationship_user_layout(llm_cfg, domain)


def build_entity_prompts(
    llm_cfg: "LLMSettings",
    domain: "DomainSettings",
) -> Tuple[str, str]:
    """Legacy helper returning (system, user_template) with {text} placeholder."""
    system, layout = build_entity_prompt_bundle(llm_cfg, domain)
    return system, layout.with_text("{text}")


def build_relationship_prompts(
    llm_cfg: "LLMSettings",
    domain: "DomainSettings",
) -> Tuple[str, str]:
    """Legacy helper returning (system, user_template) with {text} and {entities}."""
    system, layout = build_relationship_prompt_bundle(llm_cfg, domain)
    return system, layout.with_text_and_entities("{text}", "{entities}")
