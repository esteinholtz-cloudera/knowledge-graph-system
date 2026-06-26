"""LLM client configured from config.yaml."""
from typing import List, Optional

from src.config.settings import LLMSettings, load_config
from src.extraction.providers.base import LLMProviderBase
from src.extraction.providers.factory import create_provider
from src.extraction.token_usage import TokenUsage, approx_tokens


class LLMClient:
    """Generate text using the configured LLM provider."""

    def __init__(self, provider: LLMProviderBase, settings: LLMSettings):
        self._provider = provider
        self._settings = settings
        self._last_token_usage = TokenUsage()

    @property
    def last_token_usage(self) -> TokenUsage:
        return self._last_token_usage

    @classmethod
    def from_config(cls, config_path: Optional[str] = None) -> "LLMClient":
        """Build client from config/config.yaml (or given path)."""
        app = load_config(config_path)
        provider = create_provider(app.llm)
        return cls(provider=provider, settings=app.llm)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stop_words: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
        progress_label: Optional[str] = None,
        # Legacy kwargs kept for backward compatibility (ignored)
        top_p: float = 0.85,
        top_k: int = 70,
        repetition_penalty: float = 1.07,
        do_sample: bool = False,
    ) -> str:
        input_text = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        result = self._provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            stop_words=stop_words,
            temperature=temperature if temperature is not None else self._settings.temperature,
            max_new_tokens=max_new_tokens if max_new_tokens is not None else self._settings.max_new_tokens,
            progress_label=progress_label,
        )
        self._last_token_usage = TokenUsage(
            tokens_in=approx_tokens(input_text),
            tokens_out=approx_tokens(result),
        )
        return result
