"""Tests for HealthService precheck."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.health import HealthService


def _mock_config():
    cfg = MagicMock()
    llm = MagicMock()
    llm.resolved_base_url.return_value = "http://localhost:11434/v1"
    llm.model = "test-model"
    llm.get_api_key.return_value = None
    res = MagicMock()
    res.enabled = True
    res.strategies = ["rule_based"]
    res.embedding_model = "embed-model"
    cfg.llm = llm
    cfg.entity_resolution = res
    return cfg


@patch("src.services.health.load_config")
@patch("httpx.get")
def test_precheck_ok(mock_get, mock_load_config):
    mock_load_config.return_value = _mock_config()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "test-model"}]}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = HealthService().check()
    assert result.ok is True
    assert any(c.get("name") == "llm_model" and c.get("ok") for c in result.checks)


@patch("src.services.health.load_config")
@patch("httpx.get")
def test_precheck_fails_when_llm_unreachable(mock_get, mock_load_config):
    mock_load_config.return_value = _mock_config()
    mock_get.side_effect = ConnectionError("refused")

    result = HealthService().check()
    assert result.ok is False
    assert any(c.get("name") == "llm_endpoint" for c in result.checks)
