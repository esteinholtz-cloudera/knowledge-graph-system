"""Constrained single-pass LLM extraction of upgrade facts (stage 5).

The only token-spending stage. Unlike the generic two-pass pipeline, this makes
*one* call per gated chunk with a tiny, schema-locked prompt and validates the
output against the closed predicate set — no separate relationship pass, no
cross-section pass, no entity-resolution LLM calls.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..json_utils import extract_json
from ..llm_client import LLMClient
from .schema import UPGRADE_PREDICATES, UpgradeFact

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You extract software upgrade facts from documentation. "
    "Return ONLY a JSON array of objects, each exactly "
    '{"subject": "...", "predicate": "...", "object": "..."}. '
    "The predicate MUST be one of: " + ", ".join(UPGRADE_PREDICATES) + ". "
    "subject/object are product names or version labels (e.g. 'CDP 7.1.9'). "
    "Emit a fact only if the text states it. If none, return []. No prose."
)

_USER_TEMPLATE = (
    "Extract upgrade facts from the text below. JSON array only.\n\n"
    "TEXT:\n{text}"
)


class UpgradeLLMExtractor:
    """Single constrained call per chunk; invalid/off-schema facts are dropped."""

    def __init__(self, llm_client: Optional[LLMClient] = None, max_new_tokens: int = 512):
        self.llm_client = llm_client or LLMClient.from_config()
        self._max_new_tokens = max_new_tokens

    def extract(self, text: str, source: str = "", progress_label: Optional[str] = None) -> List[UpgradeFact]:
        response = self.llm_client.generate(
            prompt=_USER_TEMPLATE.format(text=text),
            system_prompt=_SYSTEM_PROMPT,
            max_new_tokens=self._max_new_tokens,
            temperature=0.1,
            progress_label=progress_label,
        )
        return self._parse(response, source)

    @staticmethod
    def _parse(response: str, source: str) -> List[UpgradeFact]:
        data = extract_json(response, prefer="array")
        if not isinstance(data, list):
            logger.warning("Upgrade extraction: no JSON array in response; skipping chunk.")
            return []
        facts: List[UpgradeFact] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            fact = UpgradeFact(
                subject=str(item.get("subject", "")),
                predicate=str(item.get("predicate", "")),
                object=str(item.get("object", "")),
                source=source,
                origin="llm",
            )
            if fact.is_valid():
                facts.append(fact)
        return facts
