"""Approximate token counts for benchmark logging."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    tokens_in: int = 0
    tokens_out: int = 0


def approx_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)
