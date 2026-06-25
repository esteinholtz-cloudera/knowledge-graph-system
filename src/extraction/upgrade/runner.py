"""Funnel orchestration: scope -> dedupe -> tables -> gated LLM -> TTL.

Ties the free filtering stages to the single paid LLM stage. The ordering is the
whole point: each step discards content before the next, costlier step runs, so
the LLM only ever sees short, upgrade-relevant prose that the deterministic
table pass did not already cover.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import httpx

from ...config.settings import load_config
from .llm_pass import UpgradeLLMExtractor
from .schema import UpgradeFact, dedupe_facts, gate_chunks
from .scoping import fetch_text, html_to_text, scope_urls
from .tables import facts_from_html
from .writer import write_upgrade_ttl

logger = logging.getLogger(__name__)

_HTML_SUFFIXES = (".html", ".htm")


def _chunk_words(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Overlapping fixed word-window chunks (self-contained, no deps)."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text] if words else []
    step = max(1, chunk_size - overlap)
    return [" ".join(words[start:start + chunk_size]) for start in range(0, len(words), step)]


@dataclass
class UpgradeRunResult:
    output_path: str
    pages: int = 0
    fact_count: int = 0
    table_facts: int = 0
    llm_facts: int = 0
    chunks_total: int = 0
    chunks_gated: int = 0
    skipped_duplicates: int = 0
    facts: List[UpgradeFact] = field(default_factory=list)


@dataclass
class UpgradeProgress:
    """One per-source progress tick, reported after each input is handled."""

    index: int          # 1-based position in the source list
    total: int          # total number of sources
    source: str         # the URL/file just handled
    status: str         # "processed" | "skipped-duplicate" | "failed"
    pages: int          # cumulative pages successfully processed
    fact_count: int     # cumulative deduped facts written to the TTL so far


ProgressCallback = Callable[[UpgradeProgress], None]


def _load_source(source: str, client: Optional[httpx.Client]) -> Optional[str]:
    """Return raw HTML/text for a URL or local file, or None on failure."""
    if source.startswith(("http://", "https://")):
        if client is None:
            return None
        try:
            return fetch_text(source, client)
        except httpx.HTTPError as exc:
            logger.warning("Fetch failed for %s: %s", source, exc)
            return None
    path = Path(source)
    if not path.exists():
        logger.warning("Local source not found: %s", source)
        return None
    return path.read_text(encoding="utf-8", errors="ignore")


def _is_html(source: str, content: str) -> bool:
    if source.startswith(("http://", "https://")) or source.lower().endswith(_HTML_SUFFIXES):
        return True
    return "<table" in content.lower()


def _llm_facts_for_page(
    extractor: UpgradeLLMExtractor,
    text: str,
    source: str,
    chunk_size: int,
    overlap: int,
) -> Tuple[List[UpgradeFact], int, int]:
    """Chunk, gate, and run the constrained LLM over signal-bearing chunks only."""
    chunks = _chunk_words(text, chunk_size, overlap)
    gated = gate_chunks(chunks)
    facts: List[UpgradeFact] = []
    for index, chunk in enumerate(gated, start=1):
        facts.extend(extractor.extract(chunk, source=source, progress_label=f"upgrade chunk {index}/{len(gated)}"))
    return facts, len(chunks), len(gated)


def _process_source(
    source: str,
    content: str,
    result: UpgradeRunResult,
    all_facts: List[UpgradeFact],
    *,
    use_llm: bool,
    extractor: Optional[UpgradeLLMExtractor],
    chunk_size: int,
    overlap: int,
) -> None:
    """Extract facts from one already-loaded source; append + update counters."""
    result.pages += 1
    if _is_html(source, content):
        table_facts = facts_from_html(content, source=source)
        result.table_facts += len(table_facts)
        all_facts.extend(table_facts)
        text = html_to_text(content)
    else:
        text = content
    if use_llm and extractor is not None:
        facts, n_chunks, n_gated = _llm_facts_for_page(extractor, text, source, chunk_size, overlap)
        result.llm_facts += len(facts)
        result.chunks_total += n_chunks
        result.chunks_gated += n_gated
        all_facts.extend(facts)


def _save_progress(result: UpgradeRunResult, all_facts: List[UpgradeFact], output_path: str) -> None:
    """Dedupe accumulated facts and persist the TTL (called after each source)."""
    result.facts = dedupe_facts(all_facts)
    result.fact_count = len(result.facts)
    result.output_path = write_upgrade_ttl(result.facts, output_path)


def _emit(
    on_progress: Optional[ProgressCallback],
    index: int,
    total: int,
    source: str,
    status: str,
    result: UpgradeRunResult,
) -> None:
    if on_progress is not None:
        on_progress(UpgradeProgress(
            index=index, total=total, source=source, status=status,
            pages=result.pages, fact_count=result.fact_count,
        ))


def run_upgrade_extraction(
    sources: List[str],
    output_path: str,
    *,
    use_llm: bool = True,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None,
    extractor: Optional[UpgradeLLMExtractor] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> UpgradeRunResult:
    """Run the funnel over URLs/files, saving the TTL after each source.

    The cumulative, deduped TTL is rewritten after every processed source, so a
    long crawl never loses completed work on interruption. ``on_progress`` (if
    given) is called once per source with an overall ``index``/``total`` count.
    """
    cfg = load_config().llm
    chunk_size = chunk_size or cfg.chunk_size
    overlap = overlap if overlap is not None else cfg.overlap
    if use_llm and extractor is None:
        extractor = UpgradeLLMExtractor()

    result = UpgradeRunResult(output_path=output_path)
    seen_hashes: set = set()
    all_facts: List[UpgradeFact] = []
    total = len(sources)

    with httpx.Client() as client:
        for index, source in enumerate(sources, start=1):
            content = _load_source(source, client)
            if content is None:
                _emit(on_progress, index, total, source, "failed", result)
                continue
            digest = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
            if digest in seen_hashes:
                result.skipped_duplicates += 1
                _emit(on_progress, index, total, source, "skipped-duplicate", result)
                continue
            seen_hashes.add(digest)
            _process_source(
                source, content, result, all_facts,
                use_llm=use_llm, extractor=extractor,
                chunk_size=chunk_size, overlap=overlap,
            )
            _save_progress(result, all_facts, output_path)  # incremental save
            _emit(on_progress, index, total, source, "processed", result)

    if result.pages == 0:
        _save_progress(result, all_facts, output_path)  # always leave a valid TTL
    result.output_path = output_path
    return result


def scope(sitemap_url: str, limit: int = 0) -> List[str]:
    """Convenience re-export: upgrade-relevant URLs from a sitemap (stage 1)."""
    return scope_urls(sitemap_url, limit=limit)
