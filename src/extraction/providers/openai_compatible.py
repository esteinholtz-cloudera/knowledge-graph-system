"""OpenAI-compatible chat API (Ollama, LM Studio, OpenAI)."""
import re
import sys
import threading
import time
from typing import List, Optional

import httpx

from .base import LLMProviderBase


class _Ticker:
    """Print a dot to stderr every `interval` seconds while a task runs."""

    def __init__(self, interval: float = 3.0):
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self._interval):
            sys.stderr.write(".")
            sys.stderr.flush()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()
        sys.stderr.write("\n")
        sys.stderr.flush()


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

        with _Ticker(), httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""

        # Thinking models (e.g. qwen3) put reasoning in reasoning_content and
        # the actual answer in content. If content is empty, fall back.
        if not content.strip():
            content = message.get("reasoning_content") or ""

        # Strip <think>...</think> blocks that some models embed inline.
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        if not content:
            raise ValueError("LLM returned empty content")
        return content
