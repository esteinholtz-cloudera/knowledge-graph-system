"""Google Gemini Generative Language API."""
from typing import List, Optional

import httpx

from .base import LLMProviderBase


class GeminiProvider(LLMProviderBase):
    """Gemini via Google Generative Language API."""

    def __init__(
        self,
        model: str,
        api_key: str,
        timeout_seconds: int = 120,
    ):
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def _api_url(self) -> str:
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )

    def generate(
        self,
        prompt: str,
        stop_words: Optional[List[str]] = None,
        temperature: float = 0.7,
        max_new_tokens: int = 512,
    ) -> str:
        url = f"{self._api_url()}?key={self.api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_new_tokens,
            },
        }
        if stop_words:
            body["generationConfig"]["stopSequences"] = stop_words

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
            data = response.json()

        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts") or []
        texts = [p.get("text", "") for p in parts if "text" in p]
        result = "".join(texts).strip()
        if not result:
            raise ValueError("Gemini returned empty content")
        return result
