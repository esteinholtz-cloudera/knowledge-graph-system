"""Create LLM provider from settings."""
from src.config.settings import LLMSettings

from .anthropic import AnthropicProvider
from .base import LLMProviderBase
from .gemini import GeminiProvider
from .openai_compatible import OpenAICompatibleProvider


def create_provider(settings: LLMSettings) -> LLMProviderBase:
    """Instantiate the configured LLM provider."""
    provider = settings.provider
    api_key = settings.get_api_key()

    if provider in ("ollama", "lmstudio", "openai"):
        return OpenAICompatibleProvider(
            base_url=settings.resolved_base_url(),
            model=settings.model,
            api_key=api_key,
            timeout_seconds=settings.timeout_seconds,
            disable_thinking=settings.disable_thinking,
        )

    if provider == "anthropic":
        if not api_key:
            env_name = settings.resolved_api_key_env() or "ANTHROPIC_API_KEY"
            raise ValueError(
                f"Anthropic requires API key; set environment variable {env_name}"
            )
        return AnthropicProvider(
            model=settings.model,
            api_key=api_key,
            timeout_seconds=settings.timeout_seconds,
        )

    if provider == "gemini":
        if not api_key:
            env_name = settings.resolved_api_key_env() or "GEMINI_API_KEY"
            raise ValueError(
                f"Gemini requires API key; set environment variable {env_name}"
            )
        return GeminiProvider(
            model=settings.model,
            api_key=api_key,
            timeout_seconds=settings.timeout_seconds,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
