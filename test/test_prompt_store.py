"""Tests for concrete per-model prompt instances on disk."""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.config.settings import DomainSettings, LLMSettings
from src.extraction.prompt_builder import build_entity_prompt_bundle
from src.extraction.prompt_store import FALLBACK_MODEL, PromptStore


def test_regenerate_writes_six_files_per_instance(tmp_path):
    store = PromptStore(tmp_path)
    llm_cfg = LLMSettings(use_few_shot=True)
    domain = DomainSettings(description="Ops docs")
    written = store.write_instance("test-model", "technical", llm_cfg, domain)
    assert len(written) == 6
    base = tmp_path / "prompts" / "test-model" / "technical"
    assert (base / "entity.system.txt").is_file()
    assert (base / "entity.user.prefix.txt").is_file()
    assert (base / "entity.user.suffix.txt").is_file()


def test_regenerate_skips_existing_without_force(tmp_path):
    store = PromptStore(tmp_path)
    llm_cfg = LLMSettings()
    domain = DomainSettings()
    store.write_instance("m", "default", llm_cfg, domain)
    again = store.write_instance("m", "default", llm_cfg, domain)
    assert again == []


def test_load_uses_concrete_files_without_substitution(tmp_path):
    store = PromptStore(tmp_path)
    base = tmp_path / "prompts" / "m1" / "default"
    base.mkdir(parents=True)
    (base / "entity.system.txt").write_text("SYSTEM ONLY", encoding="utf-8")
    (base / "entity.user.prefix.txt").write_text("PREFIX", encoding="utf-8")
    (base / "entity.user.suffix.txt").write_text("SUFFIX", encoding="utf-8")
    (base / "relationship.system.txt").write_text("REL SYS", encoding="utf-8")
    (base / "relationship.user.prefix.txt").write_text("REL PRE", encoding="utf-8")
    (base / "relationship.user.suffix.txt").write_text("REL SUF", encoding="utf-8")

    system, layout = store.load_entity_prompts(
        model_name="m1",
        domain_name="default",
        llm_cfg=LLMSettings(),
        domain=DomainSettings(),
    )
    assert system == "SYSTEM ONLY"
    assert layout.with_text("chunk") == "PREFIXchunkSUFFIX"


def test_load_matches_builder_when_unmodified(tmp_path):
    store = PromptStore(tmp_path)
    llm_cfg = LLMSettings(format_strictness="medium", use_few_shot=True)
    domain = DomainSettings(description="Test domain")
    store.write_instance("m1", "default", llm_cfg, domain)

    from_builder = build_entity_prompt_bundle(llm_cfg, domain)
    from_files = store.load_entity_prompts(
        model_name="m1",
        domain_name="default",
        llm_cfg=llm_cfg,
        domain=domain,
    )
    assert from_files == from_builder
    assert from_files[1].with_text("hello") == from_builder[1].with_text("hello")


def test_load_falls_back_across_model_and_domain(tmp_path):
    store = PromptStore(tmp_path)
    llm_cfg = LLMSettings()
    domain = DomainSettings()
    store.write_instance(FALLBACK_MODEL, "technical", llm_cfg, domain)

    system, _ = store.load_entity_prompts(
        model_name="unknown-model",
        domain_name="technical",
        llm_cfg=llm_cfg,
        domain=domain,
    )
    assert "meaningful entities" in system


def test_load_falls_back_to_builder_when_files_missing(tmp_path):
    store = PromptStore(tmp_path)
    llm_cfg = LLMSettings()
    domain = DomainSettings()
    expected = build_entity_prompt_bundle(llm_cfg, domain)
    loaded = store.load_entity_prompts(
        model_name="missing",
        domain_name="missing",
        llm_cfg=llm_cfg,
        domain=domain,
    )
    assert loaded == expected


def test_snapshot_for_run_reads_all_six_files(tmp_path):
    store = PromptStore(tmp_path)
    llm_cfg = LLMSettings(chunk_size=120, overlap=30, section_size=3)
    domain = DomainSettings(description="Ops docs")
    store.write_instance("m1", "technical", llm_cfg, domain, force=True)

    snapshot = store.snapshot_for_run(
        model_name="m1",
        domain_name="technical",
        llm_cfg=llm_cfg,
        domain=domain,
    )

    assert snapshot["domain"] == "technical"
    assert snapshot["chunk_size"] == 120
    assert snapshot["overlap"] == 30
    assert len(snapshot["files"]) == 6
    assert "entity.system.txt" in snapshot["files"]
