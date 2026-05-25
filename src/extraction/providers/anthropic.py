"""Anthropic Messages API."""
from typing import List, Optional

import httpx

from .base import LLMProviderBase


class AnthropicProvider(LLMProviderBase):
    """Claude via Anthropic Messages API."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        model: str,
        api_key: str,
        timeout_seconds: int = 120,
    ):
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(
        self,
        prompt: str,
        stop_words: Optional[List[str]] = None,
        temperature: float = 0.7,
        max_new_tokens: int = 512,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": self.model,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if stop_words:
            body["stop_sequences"] = stop_words

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.API_URL, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        content_blocks = data.get("content") or []
        texts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        result = "".join(texts).strip()
        if not result:
            raise ValueError("Anthropic returned empty content")
        return result
