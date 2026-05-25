"""LLM client configured from config.yaml."""
from pathlib import Path
from typing import List, Optional

from src.config.settings import AppSettings, LLMSettings, load_config
from src.extraction.providers.base import LLMProviderBase
from src.extraction.providers.factory import create_provider


class LLMClient:
    """Generate text using the configured LLM provider."""

    def __init__(
        self,
        provider: LLMProviderBase,
        settings: LLMSettings,
    ):
        self._provider = provider
        self._settings = settings

    @classmethod
    def from_config(cls, config_path: Optional[str] = None) -> "LLMClient":
        """Build client from config/config.yaml (or given path)."""
        app = load_config(config_path)
        provider = create_provider(app.llm)
        return cls(provider=provider, settings=app.llm)

    def generate(
        self,
        prompt: str,
        stop_words: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
        top_p: float = 0.85,
        top_k: int = 70,
        repetition_penalty: float = 1.07,
        do_sample: bool = False,
    ) -> str:
        """
        Generate text using the LLM.

        top_p, top_k, repetition_penalty, do_sample are ignored (provider-specific APIs).
        """
        if stop_words is None:
            stop_words = ["\n\n", "```", "JSON"]

        return self._provider.generate(
            prompt=prompt,
            stop_words=stop_words,
            temperature=temperature if temperature is not None else self._settings.temperature,
            max_new_tokens=max_new_tokens if max_new_tokens is not None else self._settings.max_new_tokens,
        )
