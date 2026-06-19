"""User-facing LLM failure messages."""
from __future__ import annotations

import httpx


class LLMError(RuntimeError):
    """LLM call failed — message is safe to show in the GUI."""


_EMPTY_RESPONSE = (
    "LLM server not responsive — received an empty response. "
    "The model may have crashed or stopped generating (common when LM Studio "
    "runs out of memory or the server restarts mid-request)."
)


def llm_error_from_exception(exc: BaseException, base_url: str = "") -> LLMError:
    """Map provider/transport exceptions to a GUI-safe message."""
    if isinstance(exc, LLMError):
        return exc

    msg = str(exc).strip()
    if msg == "LLM returned empty content":
        return LLMError(_EMPTY_RESPONSE)

    if isinstance(exc, httpx.ConnectError):
        target = base_url or "the configured LLM server"
        return LLMError(
            f"LLM server not reachable — cannot connect to {target}. "
            "Is the LLM server running?"
        )

    if isinstance(exc, httpx.TimeoutException):
        return LLMError(
            "LLM server not responsive — the request timed out. "
            "The model may be overloaded, stuck, or no longer running."
        )

    if isinstance(exc, httpx.RemoteProtocolError):
        return LLMError(
            "LLM server not responsive — the connection closed unexpectedly. "
            "The model may have crashed or restarted during generation."
        )

    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (502, 503, 504):
            return LLMError(
                f"LLM server not responsive — the server returned HTTP {code}."
            )
        return LLMError(f"LLM request failed — HTTP {code} from the LLM server.")

    lowered = msg.lower()
    if "connection refused" in lowered or "connect" in lowered and "failed" in lowered:
        target = base_url or "the configured LLM server"
        return LLMError(
            f"LLM server not reachable — cannot connect to {target}. "
            "Is the LLM server running?"
        )
    if "peer closed" in lowered or "incomplete message body" in lowered:
        return LLMError(
            "LLM server not responsive — the connection closed unexpectedly. "
            "The model may have crashed or restarted during generation."
        )
    if "timed out" in lowered or "timeout" in lowered:
        return LLMError(
            "LLM server not responsive — the request timed out. "
            "The model may be overloaded, stuck, or no longer running."
        )

    return LLMError(f"LLM request failed — {msg}")


def job_error_message(exc: BaseException) -> str:
    """Format any pipeline exception for job status / SSE."""
    if isinstance(exc, LLMError) or type(exc).__name__ == "ExtractionError":
        return str(exc)
    return str(llm_error_from_exception(exc))
