"""Relationship extraction from text using LLM."""
import logging
from typing import Dict, List, Optional

from .json_utils import extract_json
from .llm_client import LLMClient
from .prompts import (
    COMBINED_EXTRACTION_SYSTEM_PROMPT,
    COMBINED_EXTRACTION_USER_PROMPT,
    RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT,
    RELATIONSHIP_EXTRACTION_USER_PROMPT,
)

logger = logging.getLogger(__name__)


class RelationshipExtractor:
    """Extract relationships between entities using LLM."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient.from_config()

    def extract(
        self,
        text: str,
        entities: Optional[List[str]] = None,
        progress_label: Optional[str] = None,
    ) -> List[Dict]:
        """
        Extract relationships from text.

        Returns:
            List of dicts with 'subject', 'predicate', 'object'.
        """
        if entities:
            entity_list = ", ".join(entities[:20])
            user_prompt = RELATIONSHIP_EXTRACTION_USER_PROMPT.format(
                text=text, entities=entity_list
            )
            response = self.llm_client.generate(
                prompt=user_prompt,
                system_prompt=RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT,
                stop_words=None,
                max_new_tokens=2048,
                temperature=0.3,
                progress_label=progress_label,
            )
            return self._parse_triples(response)
        else:
            user_prompt = COMBINED_EXTRACTION_USER_PROMPT.format(text=text)
            response = self.llm_client.generate(
                prompt=user_prompt,
                system_prompt=COMBINED_EXTRACTION_SYSTEM_PROMPT,
                stop_words=None,
                max_new_tokens=2048,
                temperature=0.3,
                progress_label=progress_label,
            )
            return self._parse_combined(response)

    def _parse_triples(self, response: str) -> List[Dict]:
        data = extract_json(response, prefer="array")
        if data is None:
            return []
        if isinstance(data, list):
            return self._filter_triples(data)
        if isinstance(data, dict):
            for key in ("triples", "relationships"):
                if key in data:
                    return self._filter_triples(data[key])
        logger.warning("Unexpected triples JSON shape: %s", type(data))
        return []

    def _parse_combined(self, response: str) -> List[Dict]:
        data = extract_json(response, prefer="object")
        if data is None:
            return []
        if isinstance(data, dict):
            for key in ("triples", "relationships"):
                if key in data:
                    return self._filter_triples(data[key])
        if isinstance(data, list):
            return self._filter_triples(data)
        return []

    @staticmethod
    def _filter_triples(raw: list) -> List[Dict]:
        """
        Validate and normalise extracted triples.
        Passes through optional 'scope' and 'strength' fields for n-ary reification.
        """
        result = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            if not (t.get("subject") and t.get("predicate") and t.get("object")):
                continue
            triple = {
                "subject":   t["subject"],
                "predicate": t["predicate"],
                "object":    t["object"],
            }
            if t.get("scope"):
                triple["scope"] = str(t["scope"]).strip()
            if t.get("strength") and t["strength"] in ("mandatory", "recommended", "conditional"):
                triple["strength"] = t["strength"]
            result.append(triple)
        return result
