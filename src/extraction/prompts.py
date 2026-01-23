"""Prompts for LLM-based entity and relationship extraction."""

ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting entities from text. 
Your task is to identify and extract all meaningful entities mentioned in the text.
An entity can be a person, organization, location, concept, product, technology, or any other significant named thing.

Return your response as a JSON array of objects, where each object has:
- "entity": the name of the entity
- "type": the type/category of the entity (e.g., "Person", "Organization", "Location", "Technology", "Concept", etc.)
- "context": a brief context or description if helpful

Be thorough and extract all significant entities. Do not include common words or generic terms unless they are specifically important in the context."""

ENTITY_EXTRACTION_USER_PROMPT = """Extract all entities from the following text. Return only valid JSON array format:

Text:
{text}

JSON:"""

RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting relationships between entities from text.
Your task is to identify relationships (predicates) that connect entities (subjects and objects).

Return your response as a JSON array of triples, where each object has:
- "subject": the source entity
- "predicate": the relationship/predicate connecting them (use concise, clear verbs like "worksFor", "locatedIn", "uses", "relatedTo", etc.)
- "object": the target entity

Only extract relationships that are explicitly stated or strongly implied in the text. Be precise with relationship types."""

RELATIONSHIP_EXTRACTION_USER_PROMPT = """Extract all relationships between entities from the following text. 
Return only valid JSON array format with triples (subject, predicate, object):

Text:
{text}

Entities found: {entities}

JSON:"""

COMBINED_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting knowledge graphs from text.
Your task is to extract entities and relationships to build a knowledge graph.

Return your response as a JSON object with two arrays:
- "entities": array of objects with "entity", "type", and optionally "context"
- "triples": array of objects with "subject", "predicate", "object"

Be thorough and extract all significant information. Use clear, concise relationship predicates."""

COMBINED_EXTRACTION_USER_PROMPT = """Extract entities and relationships from the following text to build a knowledge graph.
Return only valid JSON format:

Text:
{text}

JSON:"""

