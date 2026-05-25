"""OpenAI-compatible chat API (Ollama, LM Studio, OpenAI)."""
from typing import List, Optional

import httpx

from .base import LLMProviderBase


class OpenAICompatibleProvider(LLMProviderBase):
    """Chat completions via OpenAI-compatible HTTP API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout_seconds: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(
        self,
        prompt: str,
        stop_words: Optional[List[str]] = None,
        temperature: float = 0.3,
        max_new_tokens: int = 1024,
        system_prompt: Optional[str] = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_new_tokens,
        }
        if stop_words:
            body["stop"] = stop_words

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None:
            raise ValueError("LLM returned empty content")
        return content.strip()
