"""User prompt layout for extraction (prefix + input + suffix)."""
from __future__ import annotations

from dataclasses import dataclass

ENTITIES_SEPARATOR = "\n\nEntities: "


@dataclass(frozen=True)
class UserPromptLayout:
    """User prompt as prefix + document input + suffix (no config placeholders)."""

    prefix: str
    suffix: str

    def with_text(self, text: str) -> str:
        return f"{self.prefix}{text}{self.suffix}"

    def with_text_and_entities(self, text: str, entities: str) -> str:
        return f"{self.prefix}{text}{ENTITIES_SEPARATOR}{entities}{self.suffix}"
