"""Base LLM provider interface."""
from abc import ABC, abstractmethod
from typing import List, Optional


class LLMProviderBase(ABC):
    """Abstract LLM backend."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        stop_words: Optional[List[str]] = None,
        temperature: float = 0.3,
        max_new_tokens: int = 1024,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate text from a prompt."""
