"""Entity extraction from text using LLM."""
import logging
from typing import Dict, List, Optional

from .json_utils import extract_json
from .llm_client import LLMClient
from .prompts import ENTITY_EXTRACTION_SYSTEM_PROMPT, ENTITY_EXTRACTION_USER_PROMPT

logger = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """Raised when the LLM response cannot be parsed into the expected structure."""


class EntityExtractor:
    """Extract entities from text using LLM."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient.from_config()

    def extract(self, text: str, progress_label: Optional[str] = None) -> List[Dict]:
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
            progress_label=progress_label,
        )

        return self._parse(response)

    def _parse(self, response: str) -> List[Dict]:
        data = extract_json(response, prefer="array")

        # No JSON found at all — LLM is not producing JSON syntax, abort.
        if data is None:
            raise ExtractionError(
                f"Entity extraction: LLM response contained no parseable JSON "
                f"(XML wrappers and markdown fences were already stripped).\n"
                f"Raw response (first 500 chars):\n{response[:500]}"
            )

        # Valid JSON, expected shapes.
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict) and e.get("entity")]
        if isinstance(data, dict) and "entities" in data:
            return [e for e in data["entities"] if isinstance(e, dict) and e.get("entity")]
        # Single entity returned as a bare dict instead of a one-element array.
        if isinstance(data, dict) and data.get("entity"):
            logger.warning("Entity extraction: model returned a single entity object instead of an array; treating as one-element list.")
            return [data]

        # Valid JSON but not a shape we can use — abort.
        raise ExtractionError(
            f"Entity extraction: JSON parsed successfully but shape is not usable "
            f"({type(data).__name__}, keys={list(data.keys()) if isinstance(data, dict) else 'n/a'}). "
            f"Expected a JSON array or {{\"entities\": [...]}}.\n"
            f"Raw response (first 500 chars):\n{response[:500]}"
        )
