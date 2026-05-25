"""Entity extraction from text using LLM."""
import logging
from typing import Dict, List, Optional

from .json_utils import extract_json
from .llm_client import LLMClient
from .prompts import ENTITY_EXTRACTION_SYSTEM_PROMPT, ENTITY_EXTRACTION_USER_PROMPT

logger = logging.getLogger(__name__)


class EntityExtractor:
    """Extract entities from text using LLM."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient.from_config()

    def extract(self, text: str) -> List[Dict]:
        """
        Extract entities from text.

        Returns:
            List of dicts with 'entity', 'type', and optionally 'context'.
        """
        user_prompt = ENTITY_EXTRACTION_USER_PROMPT.format(text=text)

        response = self.llm_client.generate(
            prompt=user_prompt,
            system_prompt=ENTITY_EXTRACTION_SYSTEM_PROMPT,
            stop_words=None,
            max_new_tokens=1024,
            temperature=0.3,
        )

        return self._parse(response)

    def _parse(self, response: str) -> List[Dict]:
        data = extract_json(response, prefer="array")
        if data is None:
            return []
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict) and e.get("entity")]
        if isinstance(data, dict) and "entities" in data:
            return [e for e in data["entities"] if isinstance(e, dict) and e.get("entity")]
        logger.warning("Unexpected entity JSON shape: %s", type(data))
        return []
