"""LLM error message formatting."""
import sys
from pathlib import Path

import httpx
import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.extraction.llm_errors import LLMError, job_error_message, llm_error_from_exception


def test_empty_response_maps_to_not_responsive():
    err = llm_error_from_exception(ValueError("LLM returned empty content"))
    assert "LLM server not responsive" in str(err)
    assert "empty response" in str(err)


def test_connect_error_maps_to_not_reachable():
    err = llm_error_from_exception(
        httpx.ConnectError("[Errno 61] Connection refused"),
        base_url="http://127.0.0.1:1234/v1",
    )
    assert "LLM server not reachable" in str(err)
    assert "127.0.0.1:1234/v1" in str(err)


def test_read_timeout_maps_to_not_responsive():
    err = llm_error_from_exception(httpx.ReadTimeout("timed out"))
    assert "LLM server not responsive" in str(err)
    assert "timed out" in str(err)


def test_remote_protocol_error_maps_to_not_responsive():
    err = llm_error_from_exception(
        httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
    )
    assert "LLM server not responsive" in str(err)
    assert "closed unexpectedly" in str(err)


def test_llm_error_passthrough():
    original = LLMError("custom")
    assert llm_error_from_exception(original) is original


def test_job_error_message_preserves_llm_error():
    msg = job_error_message(LLMError("LLM server not responsive — test"))
    assert msg == "LLM server not responsive — test"
