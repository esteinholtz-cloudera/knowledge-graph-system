"""Prompts for LLM-based entity and relationship extraction."""

ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting named entities from text.

Extract all meaningful entities (persons, organisations, locations, technologies, concepts, products, events, dates).

Return ONLY a JSON array — no explanation, no markdown, no preamble. Each element must have:
- "entity": the entity name exactly as it appears in the text
- "type": one of Person | Organization | Location | Technology | Concept | Product | Event | Date | Other
- "context": one short phrase describing the entity's role in the text"""

ENTITY_EXTRACTION_USER_PROMPT = """Text:
{text}

JSON array (no preamble):"""

RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting relationships between entities from text.

Return ONLY a JSON array of triples — no explanation, no markdown, no preamble. Each element must have:
- "subject": source entity name
- "predicate": concise camelCase verb (e.g. worksFor, locatedIn, uses, partOf)
- "object": target entity name

Only include relationships explicitly stated or strongly implied."""

RELATIONSHIP_EXTRACTION_USER_PROMPT = """Text:
{text}

Entities: {entities}

JSON array of triples (no preamble):"""

COMBINED_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting knowledge graphs from text.

Return ONLY a JSON object — no explanation, no markdown, no preamble — with two keys:
- "entities": array of objects with "entity", "type", "context"
- "triples": array of objects with "subject", "predicate", "object"

Types: Person | Organization | Location | Technology | Concept | Product | Event | Date | Other
Predicates: concise camelCase verbs (worksFor, uses, locatedIn, partOf, relatedTo, …)"""

COMBINED_EXTRACTION_USER_PROMPT = """Text:
{text}

JSON object (no preamble):"""
