"""Approximate token counts for benchmark logging."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class TokenUsage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class GenerationResult:
    """Text returned by an LLM call plus the call's approximate token usage."""
    text: str
    usage: TokenUsage


@dataclass(frozen=True)
class Extracted:
    """Parsed extraction output plus the token usage of the call that produced it."""
    items: List[dict]
    usage: TokenUsage


def approx_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)
