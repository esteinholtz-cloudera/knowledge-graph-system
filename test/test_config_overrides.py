"""Tests for config.yaml CLI overrides."""
import pytest
from pydantic import ValidationError

from src.config.settings import (
    AppSettings,
    clear_cli_overrides,
    load_config,
    overrides_from_cli,
    set_cli_overrides,
)


@pytest.fixture(autouse=True)
def _reset_cli_overrides():
    clear_cli_overrides()
    yield
    clear_cli_overrides()


def test_overrides_from_cli_nested_keys():
    data = overrides_from_cli(
        [
            "llm.temperature=0.9",
            "llm.model_settings.qwen3.chunk_size=150",
            "entity_resolution.enabled=false",
        ]
    )
    assert data == {
        "llm": {
            "temperature": 0.9,
            "model_settings": {"qwen3": {"chunk_size": 150}},
        },
        "entity_resolution": {"enabled": False},
    }


def test_overrides_from_cli_parses_types():
    data = overrides_from_cli(
        [
            "llm.model=null",
            "pipeline.max_concurrent_llm_calls=4",
            "entity_resolution.strategies=[\"embedding\",\"llm\"]",
            "storage.knowledge_graphs_dir='custom/path'",
        ]
    )
    assert data["llm"]["model"] is None
    assert data["pipeline"]["max_concurrent_llm_calls"] == 4
    assert data["entity_resolution"]["strategies"] == ["embedding", "llm"]
    assert data["storage"]["knowledge_graphs_dir"] == "custom/path"


def test_overrides_from_cli_rejects_invalid_pair():
    with pytest.raises(ValueError, match="KEY=VALUE"):
        overrides_from_cli(["llm.temperature"])


def test_load_config_applies_programmatic_overrides():
    app = load_config(overrides={"llm": {"temperature": 0.77}})
    assert app.llm.temperature == 0.77


def test_load_config_applies_cli_overrides():
    set_cli_overrides({"llm": {"provider": "ollama", "chunk_size": 42}})
    app = load_config()
    assert app.llm.provider == "ollama"
    assert app.llm.chunk_size == 42


def test_load_config_deep_merges_model_settings():
    set_cli_overrides(
        overrides_from_cli(["llm.model_settings.qwen3-30b-a3b-instruct-2507-mlx.overlap=99"])
    )
    app = load_config()
    model_cfg = app.llm.model_settings["qwen3-30b-a3b-instruct-2507-mlx"]
    assert model_cfg.overlap == 99
    assert model_cfg.chunk_size == 100


def test_load_config_rejects_invalid_override():
    with pytest.raises(ValidationError):
        load_config(overrides={"llm": {"provider": "not-a-provider"}})
