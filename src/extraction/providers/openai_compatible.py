"""OpenAI-compatible chat API (Ollama, LM Studio, OpenAI)."""
import json
import re
import sys
from typing import List, Optional

import httpx

from src.extraction.llm_errors import LLMError, llm_error_from_exception

from .base import LLMProviderBase


class OpenAICompatibleProvider(LLMProviderBase):
    """Chat completions via OpenAI-compatible HTTP API."""

    def __init__(
        self,
        base_url: str,
        model: Optional[str],
        api_key: Optional[str] = None,
        timeout_seconds: int = 120,
        disable_thinking: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self._configured_model = model  # None = auto-detect
        self._resolved_model: Optional[str] = None  # cached after first detection
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.disable_thinking = disable_thinking

    @property
    def model(self) -> str:
        """Return the resolved model name, auto-detecting if necessary."""
        if self._resolved_model:
            return self._resolved_model
        if self._configured_model:
            self._resolved_model = self._configured_model
            return self._resolved_model
        # Auto-detect: use the first model listed by the server
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{self.base_url}/models", headers=headers)
                resp.raise_for_status()
                models = resp.json().get("data", [])
                if not models:
                    raise ValueError("No models available on the server")
                self._resolved_model = models[0]["id"]
                import sys
                sys.stderr.write(f"[auto] model: {self._resolved_model}\n")
                return self._resolved_model
        except Exception as e:
            raise ValueError(f"Could not auto-detect model from {self.base_url}/models: {e}")

    def generate(
        self,
        prompt: str,
        stop_words: Optional[List[str]] = None,
        temperature: float = 0.3,
        max_new_tokens: int = 1024,
        system_prompt: Optional[str] = None,
        progress_label: Optional[str] = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        effective_system = system_prompt or ""
        if self.disable_thinking and effective_system:
            effective_system = "/no_think\n" + effective_system
        elif self.disable_thinking:
            effective_system = "/no_think"

        messages = []
        if effective_system:
            messages.append({"role": "system", "content": effective_system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_new_tokens,
            "stream": True,
        }
        if stop_words:
            body["stop"] = stop_words

        label = f"[{progress_label}]" if progress_label else ""
        content = ""
        reasoning_content = ""
        token_count = 0

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream("POST", url, json=body, headers=headers) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            token = delta.get("content") or ""
                            reasoning_token = delta.get("reasoning_content") or ""
                            if token:
                                content += token
                                token_count += 1
                            if reasoning_token:
                                reasoning_content += reasoning_token
                                token_count += 1
                            pct = min(99, token_count * 100 // max_new_tokens)
                            sys.stderr.write(f"\r{label} {pct:3d}%  ")
                            sys.stderr.flush()
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except httpx.HTTPError as exc:
            raise llm_error_from_exception(exc, self.base_url) from exc

        sys.stderr.write(f"\r{label} 100%\n")
        sys.stderr.flush()

        # Thinking models put answer in content, reasoning in reasoning_content.
        # If content is empty, fall back to reasoning_content.
        result = content.strip() or reasoning_content.strip()

        # Strip inline <think> blocks.
        result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()

        if not result:
            raise LLMError(
                "LLM server not responsive — received an empty response. "
                "The model may have crashed or stopped generating (common when LM Studio "
                "runs out of memory or the server restarts mid-request)."
            )
        return result
