"""Funnel orchestration: scope -> dedupe -> tables -> gated LLM -> TTL.

Ties the free filtering stages to the single paid LLM stage. The ordering is the
whole point: each step discards content before the next, costlier step runs, so
the LLM only ever sees short, upgrade-relevant prose that the deterministic
table pass did not already cover.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import httpx
from rdflib import Graph

from ...config.settings import load_config
from .llm_pass import UpgradeLLMExtractor
from .schema import UpgradeFact, gate_chunks
from .scoping import fetch_text, html_to_text, scope_urls
from .tables import facts_from_html
from .writer import add_facts, count_facts, load_graph, new_graph, serialize_graph

logger = logging.getLogger(__name__)

_HTML_SUFFIXES = (".html", ".htm")
_MANIFEST_SUFFIX = ".manifest.json"


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
    manifest_path: str = ""
    pages: int = 0
    fact_count: int = 0
    table_facts: int = 0
    llm_facts: int = 0
    chunks_total: int = 0
    chunks_gated: int = 0
    skipped_duplicates: int = 0
    already_done: int = 0  # sources skipped because a prior run finished them
    facts: List[UpgradeFact] = field(default_factory=list)


@dataclass
class UpgradeProgress:
    """One per-source progress tick, reported after each input is handled."""

    index: int          # 1-based position in the source list
    total: int          # total number of sources
    source: str         # the URL/file just handled
    status: str         # processed | skipped-duplicate | skipped-done | failed
    pages: int          # cumulative pages processed this run
    fact_count: int     # cumulative facts in the TTL so far


ProgressCallback = Callable[[UpgradeProgress], None]


def _manifest_path(output_path: str) -> str:
    return output_path + _MANIFEST_SUFFIX


def _load_manifest(output_path: str) -> Dict[str, str]:
    """Return the {source: content_hash} map of already-finished sources."""
    path = Path(_manifest_path(output_path))
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data.get("processed", {}))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Ignoring unreadable manifest %s: %s", path, exc)
        return {}


def _save_manifest(output_path: str, processed: Dict[str, str]) -> str:
    """Atomically persist the processed-source map (temp file + rename)."""
    path = Path(_manifest_path(output_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps({"processed": processed}), encoding="utf-8")
    os.replace(tmp_path, path)
    return str(path)


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
    graph: Graph,
    *,
    use_llm: bool,
    extractor: Optional[UpgradeLLMExtractor],
    chunk_size: int,
    overlap: int,
) -> None:
    """Extract facts from one source, merge into graph, update counters."""
    result.pages += 1
    new_facts: List[UpgradeFact] = []
    if _is_html(source, content):
        table_facts = facts_from_html(content, source=source)
        result.table_facts += len(table_facts)
        new_facts.extend(table_facts)
        text = html_to_text(content)
    else:
        text = content
    if use_llm and extractor is not None:
        facts, n_chunks, n_gated = _llm_facts_for_page(extractor, text, source, chunk_size, overlap)
        result.llm_facts += len(facts)
        result.chunks_total += n_chunks
        result.chunks_gated += n_gated
        new_facts.extend(facts)
    add_facts(graph, new_facts)


def _persist(
    graph: Graph,
    processed: Dict[str, str],
    output_path: str,
    result: UpgradeRunResult,
) -> None:
    """Save TTL + manifest after a source and refresh the cumulative fact count."""
    result.output_path = serialize_graph(graph, output_path)
    result.manifest_path = _save_manifest(output_path, processed)
    result.fact_count = count_facts(graph)


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
    resume: bool = True,
) -> UpgradeRunResult:
    """Run the funnel over URLs/files, saving the TTL after each source.

    The cumulative TTL is rewritten after every source and a sidecar manifest
    (``<output>.manifest.json``) records finished sources by content hash. When
    ``resume`` is True (default) a re-run loads both, skips sources already done
    (including zero-fact pages, so they are not re-fetched), and merges new facts
    into the existing graph. ``on_progress`` is called once per source.
    """
    cfg = load_config().llm
    chunk_size = chunk_size or cfg.chunk_size
    overlap = overlap if overlap is not None else cfg.overlap
    if use_llm and extractor is None:
        extractor = UpgradeLLMExtractor()

    result = UpgradeRunResult(output_path=output_path)
    processed = _load_manifest(output_path) if resume else {}
    graph = load_graph(output_path) if resume else new_graph()
    seen_hashes = set(processed.values())
    result.fact_count = count_facts(graph)
    total = len(sources)

    with httpx.Client() as client:
        for index, source in enumerate(sources, start=1):
            if source in processed:
                result.already_done += 1
                _emit(on_progress, index, total, source, "skipped-done", result)
                continue
            content = _load_source(source, client)
            if content is None:
                _emit(on_progress, index, total, source, "failed", result)
                continue
            digest = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
            processed[source] = digest  # record so resume never re-fetches it
            if digest in seen_hashes:
                result.skipped_duplicates += 1
                _persist(graph, processed, output_path, result)
                _emit(on_progress, index, total, source, "skipped-duplicate", result)
                continue
            seen_hashes.add(digest)
            _process_source(
                source, content, result, graph,
                use_llm=use_llm, extractor=extractor,
                chunk_size=chunk_size, overlap=overlap,
            )
            _persist(graph, processed, output_path, result)  # incremental save
            _emit(on_progress, index, total, source, "processed", result)

    if not Path(output_path).exists():
        _persist(graph, processed, output_path, result)  # always leave a valid TTL
    result.output_path = output_path
    return result


def scope(sitemap_url: str, limit: int = 0) -> List[str]:
    """Convenience re-export: upgrade-relevant URLs from a sitemap (stage 1)."""
    return scope_urls(sitemap_url, limit=limit)
