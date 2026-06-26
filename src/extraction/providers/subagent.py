"""Cursor subagent used as an LLM backend (via the `cursor-agent` CLI).

The subagent *is* the LLM: whatever model the subagent runs is the model used
for generation. Each generate() call spawns a headless, non-interactive agent
(`--print`) in read-only "ask" mode so it only answers and never edits the
workspace.

The agent owns its own sampling parameters, so temperature / max_new_tokens are
not forwarded — "the LLM is identical to what the subagent provides". stop_words
are honoured by truncating the returned text (the CLI has no stop-sequence flag).
"""
import shutil
import subprocess
from typing import List, Optional

from src.extraction.llm_errors import LLMError

from .base import LLMProviderBase


class SubagentProvider(LLMProviderBase):
    """Run prompts through a Cursor subagent via the `cursor-agent` CLI."""

    def __init__(
        self,
        model: Optional[str],
        cli_path: str = "cursor-agent",
        timeout_seconds: int = 120,
        mode: str = "ask",
        workspace: Optional[str] = None,
    ):
        self._configured_model = model  # None = let the subagent pick its default
        self.cli_path = cli_path
        self.timeout_seconds = timeout_seconds
        self.mode = mode
        self.workspace = workspace

    @property
    def model(self) -> str:
        """Model label used for config overrides and benchmark logging."""
        return self._configured_model or "subagent-default"

    def _build_command(self, full_prompt: str) -> List[str]:
        cmd = [self.cli_path, "--print", "--output-format", "text"]
        if self.mode:
            cmd += ["--mode", self.mode]
        if self._configured_model:
            cmd += ["--model", self._configured_model]
        if self.workspace:
            cmd += ["--workspace", self.workspace]
        cmd.append(full_prompt)
        return cmd

    def generate(
        self,
        prompt: str,
        stop_words: Optional[List[str]] = None,
        temperature: float = 0.3,
        max_new_tokens: int = 1024,
        system_prompt: Optional[str] = None,
        progress_label: Optional[str] = None,
    ) -> str:
        if not shutil.which(self.cli_path) and "/" not in self.cli_path:
            raise LLMError(
                f"Subagent CLI {self.cli_path!r} not found on PATH. "
                "Install the Cursor CLI and run `cursor-agent login`, or set "
                "llm.subagent_cli in config.yaml."
            )

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        cmd = self._build_command(full_prompt)

        try:
            completed = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,  # headless --print blocks on an open stdin
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                "Subagent not responsive — the request timed out. "
                "The model may be overloaded, stuck, or no longer running."
            ) from exc
        except FileNotFoundError as exc:
            raise LLMError(
                f"Subagent CLI {self.cli_path!r} could not be launched ({exc})."
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise LLMError(f"Subagent request failed (exit {completed.returncode}) — {detail}")

        result = (completed.stdout or "").strip()
        if not result:
            raise LLMError(
                "Subagent returned an empty response. The agent may have failed "
                "to authenticate or produced no output."
            )

        if stop_words:
            cuts = [result.find(w) for w in stop_words if w and w in result]
            if cuts:
                result = result[: min(cuts)].strip()

        return result
