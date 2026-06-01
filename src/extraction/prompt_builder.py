"""
Build extraction prompts from LLM settings and domain configuration.

Prompts are composed from three layers:
  1. Structure   — fixed schema and field definitions (same for all models/domains)
  2. Vocabulary  — entity types and predicate list (domain-specific, merged with defaults)
  3. Format      — JSON-only enforcement and optional few-shot example (model-specific)

Call build_entity_prompts() / build_relationship_prompts() at the start of each
extraction run to get the (system_prompt, user_prompt_template) pair for that
model + domain combination.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

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

# Per-strictness suffix appended to the JSON-only instruction.
_FORMAT_SUFFIX = {
    "low": "",
    "medium": " Start your response with [ and end with ].",
    "high": ' Start with [ and end with ]. Do NOT write any text outside the JSON.',
}

# Few-shot example injected into the user prompt for models that need it.
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


def build_entity_prompts(
    llm_cfg: "LLMSettings",
    domain: "DomainSettings",
) -> Tuple[str, str]:
    """
    Build entity extraction (system_prompt, user_prompt_template).
    user_prompt_template contains {text} placeholder.
    """
    types = _merged_types(domain)
    type_list = " | ".join(types)
    strictness = llm_cfg.format_strictness
    format_suffix = _FORMAT_SUFFIX.get(strictness, "")
    domain_hint = f"\nDomain context: {domain.description}." if domain.description else ""

    system = (
        f"You are an expert at extracting named entities from text.{domain_hint}\n\n"
        f"Extract all meaningful entities.\n\n"
        f"Return ONLY a JSON array — no explanation, no markdown, no preamble.{format_suffix} "
        f"Each element must have:\n"
        f'- "entity": the entity name exactly as it appears in the text\n'
        f'- "type": one of {type_list}\n'
        f'- "context": one short phrase describing the entity\'s role in the text'
    )

    few_shot = _EE_FEW_SHOT if llm_cfg.use_few_shot else ""
    user_template = f"{few_shot}Text:\n{{text}}\n\nJSON array (no preamble):"

    return system, user_template


def build_relationship_prompts(
    llm_cfg: "LLMSettings",
    domain: "DomainSettings",
) -> Tuple[str, str]:
    """
    Build relationship extraction (system_prompt, user_prompt_template).
    user_prompt_template contains {text} and {entities} placeholders.
    """
    predicates = _merged_predicates(domain)
    pred_list = ", ".join(predicates)
    strictness = llm_cfg.format_strictness
    format_suffix = _FORMAT_SUFFIX.get(strictness, "")
    domain_hint = f"\nDomain context: {domain.description}." if domain.description else ""

    system = (
        f"You are an expert at extracting relationships between entities from text.{domain_hint}\n\n"
        f"Return ONLY a JSON array of triples — no explanation, no markdown, no preamble.{format_suffix} "
        f"Each element must have:\n"
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

    few_shot = _RE_FEW_SHOT if llm_cfg.use_few_shot else ""
    user_template = f"{few_shot}Text:\n{{text}}\n\nEntities: {{entities}}\n\nJSON array of triples (no preamble):"

    return system, user_template
