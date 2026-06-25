"""Full document processing and knowledge graph extraction pipeline."""
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from src.config.settings import AppSettings, LLMSettings, load_config
from src.document.html_markup import HTMLMarkupGenerator
from src.document.processor import DocumentProcessor
from src.extraction.entity_extractor import EntityExtractor, ExtractionError
from src.extraction.entity_resolver import EntityResolver
from src.extraction.llm_errors import LLMError
from src.extraction.prompt_store import PromptStore
from src.extraction.relationship_extractor import RelationshipExtractor
from src.services.artifacts import ArtifactService
from src.services.jobs import JobCancelled
from src.services.models import ChunkPlan, EntityPassResult, PipelineOptions, PipelineResult
from src.services.progress import (
    CliProgressReporter,
    ProgressEvent,
    ProgressReporter,
    format_eta,
)
from src.storage.benchmark_store import create_benchmark_store
from src.storage.metadata_store import MetadataStore
from src.storage.rdf_utils import canonical_match_key, normalise_whitespace
from src.storage.turtle_writer import TurtleWriter


_LLM_ERROR_HINTS = [
    "Ensure LM Studio (or your configured LLM server) is running with a model loaded",
    "Restart the LLM server if it crashed or ran out of memory",
    "Use max chunks = 1 to test a single chunk before a full run",
]


def _emit_llm_failure(
    reporter: ProgressReporter,
    exc: Exception,
    *,
    chunk_num: int,
    total_chunks: int,
    kind: str,
    hints: Optional[List[str]] = None,
) -> None:
    reporter.emit(ProgressEvent(
        stage="error",
        chunk=chunk_num,
        total_chunks=total_chunks,
        message=str(exc),
        payload={
            "kind": kind,
            "chunk_num": chunk_num,
            "total_chunks": total_chunks,
            "detail": str(exc),
            "hints": hints or _LLM_ERROR_HINTS,
        },
    ))


@dataclass
class _RunContext:
    options: PipelineOptions
    reporter: ProgressReporter
    cancel_check: Optional[Callable[[], bool]]
    app_config: AppSettings
    llm_cfg: LLMSettings
    entity_extractor: EntityExtractor
    relationship_extractor: RelationshipExtractor
    doc_data: Dict[str, Any]
    document_id: str
    chunks: List[str]
    run_id: str
    bench: Any
    run_start: float
    max_concurrent: int = 1
    chunk_entity_counts: List[int] = field(default_factory=list)

    def ensure_not_cancelled(self) -> None:
        if self.cancel_check and self.cancel_check():
            raise JobCancelled("pipeline cancelled")


def _run_chunks_in_order(
    ctx: _RunContext,
    stage: str,
    items: List[str],
    work: Callable[[int, str], Any],
    progress_suffix: str,
    on_done: Callable[[int, Any, float], None],
) -> None:
    """Run per-chunk work with optional parallelism; emit progress in chunk order."""
    total = len(items)
    if total == 0:
        return

    chunk_times: List[float] = []
    workers = max(1, min(ctx.max_concurrent, total))

    if workers == 1:
        for i, item in enumerate(items):
            ctx.ensure_not_cancelled()
            _run_single_chunk(ctx, stage, i, item, total, chunk_times, work, progress_suffix, on_done)
        return

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            i: pool.submit(work, i, items[i])
            for i in range(total)
        }
        for i in range(total):
            ctx.ensure_not_cancelled()
            chunk_num = i + 1
            eta_str = format_eta(chunk_times, total - i)
            ctx.reporter.emit(ProgressEvent(
                stage=stage,
                chunk=chunk_num,
                total_chunks=total,
                payload={"kind": "chunk_header", "eta_str": eta_str},
            ))
            t0 = time.monotonic()
            result = futures[i].result()
            elapsed = time.monotonic() - t0
            chunk_times.append(elapsed)
            on_done(i, result, elapsed)


def _run_single_chunk(
    ctx: _RunContext,
    stage: str,
    index: int,
    item: str,
    total: int,
    chunk_times: List[float],
    work: Callable[[int, str], Any],
    progress_suffix: str,
    on_done: Callable[[int, Any, float], None],
) -> None:
    chunk_num = index + 1
    eta_str = format_eta(chunk_times, total - index)
    ctx.reporter.emit(ProgressEvent(
        stage=stage,
        chunk=chunk_num,
        total_chunks=total,
        payload={"kind": "chunk_header", "eta_str": eta_str},
    ))
    t0 = time.monotonic()
    result = work(index, item)
    elapsed = time.monotonic() - t0
    chunk_times.append(elapsed)
    on_done(index, result, elapsed)


class PipelineService:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        entity_extractor_factory: Type[EntityExtractor] = EntityExtractor,
        relationship_extractor_factory: Type[RelationshipExtractor] = RelationshipExtractor,
        document_processor_factory: Type[DocumentProcessor] = DocumentProcessor,
        artifact_service: Optional[ArtifactService] = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._entity_extractor_factory = entity_extractor_factory
        self._relationship_extractor_factory = relationship_extractor_factory
        self._document_processor_factory = document_processor_factory
        self._artifacts = artifact_service or ArtifactService(self.project_root)

    def run(
        self,
        options: PipelineOptions,
        reporter: Optional[ProgressReporter] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> PipelineResult:
        rep = reporter or CliProgressReporter()
        ctx = self._build_plan(options, rep, cancel_check)
        try:
            entity_result = self._extract_entities(ctx)
            unique_entities = self._resolve_entities(ctx, entity_result)
            all_triples = self._extract_relationships(ctx, unique_entities)
            return self._write_outputs(
                ctx, all_triples, unique_entities, entity_result.entities_raw,
            )
        except ExtractionError:
            ctx.bench.close()
            raise
        except LLMError:
            ctx.bench.close()
            raise

    def _build_plan(
        self,
        options: PipelineOptions,
        reporter: ProgressReporter,
        cancel_check: Optional[Callable[[], bool]],
    ) -> _RunContext:
        reporter.emit(ProgressEvent(
            stage="plan",
            payload={"kind": "processing_start", "file_path": options.file_path},
        ))

        app_config = load_config()
        entity_extractor = self._entity_extractor_factory()
        resolved_model = entity_extractor.llm_client._provider.model
        llm_cfg = app_config.llm.for_model(resolved_model)
        domain_cfg = app_config.get_domain(options.domain)

        if options.domain != "default":
            reporter.emit(ProgressEvent(
                stage="plan",
                payload={
                    "kind": "domain",
                    "domain": options.domain,
                    "description": domain_cfg.description or "",
                },
            ))

        entity_extractor = self._entity_extractor_factory(
            llm_client=entity_extractor.llm_client,
            llm_cfg=llm_cfg,
            domain=domain_cfg,
            domain_name=options.domain,
            model_name=resolved_model,
            prompt_store=PromptStore(self.project_root),
        )
        relationship_extractor = self._relationship_extractor_factory(
            llm_cfg=llm_cfg,
            domain=domain_cfg,
            domain_name=options.domain,
            model_name=resolved_model,
            prompt_store=PromptStore(self.project_root),
        )

        processor = self._document_processor_factory(
            chunk_size=llm_cfg.chunk_size,
            overlap=llm_cfg.overlap,
            chunk_strategy=llm_cfg.chunk_strategy,
        )
        doc_data = processor.process_document(options.file_path)
        document_id = Path(doc_data["filename"]).stem

        chunks = processor.chunk_text(doc_data["text"])
        if options.max_chunks and len(chunks) > options.max_chunks:
            chunks_msg = f"Split into {len(chunks)} chunks (limiting to first {options.max_chunks})"
            chunks = chunks[:options.max_chunks]
        else:
            chunks_msg = f"Split into {len(chunks)} chunks"

        reporter.emit(ProgressEvent(
            stage="plan",
            payload={
                "kind": "document_info",
                "filename": doc_data["filename"],
                "word_count": doc_data["word_count"],
                "chunks_message": chunks_msg,
            },
        ))

        bench = create_benchmark_store()
        prompt_store = PromptStore(self.project_root)
        run_snapshot = prompt_store.snapshot_for_run(
            model_name=resolved_model,
            domain_name=options.domain,
            llm_cfg=llm_cfg,
            domain=domain_cfg,
        )
        run_id = bench.start_run(
            document_filename=doc_data["filename"],
            document_id=document_id,
            word_count=doc_data["word_count"],
            llm_provider=app_config.llm.provider,
            llm_model=resolved_model,
            resolution_enabled=app_config.entity_resolution.enabled,
            resolution_strategies=list(app_config.entity_resolution.strategies),
            max_chunks=options.max_chunks,
            run_snapshot_json=PromptStore.snapshot_to_json(run_snapshot),
        )

        return _RunContext(
            options=options,
            reporter=reporter,
            cancel_check=cancel_check,
            app_config=app_config,
            llm_cfg=llm_cfg,
            entity_extractor=entity_extractor,
            relationship_extractor=relationship_extractor,
            doc_data=doc_data,
            document_id=document_id,
            chunks=chunks,
            run_id=run_id,
            bench=bench,
            run_start=time.monotonic(),
            max_concurrent=max(1, app_config.pipeline.max_concurrent_llm_calls),
        )

    def build_plan(self, options: PipelineOptions) -> ChunkPlan:
        """Document chunking plan only (no benchmark run, no extraction)."""
        app_config = load_config()
        entity_extractor = self._entity_extractor_factory()
        resolved_model = entity_extractor.llm_client._provider.model
        llm_cfg = app_config.llm.for_model(resolved_model)
        processor = self._document_processor_factory(
            chunk_size=llm_cfg.chunk_size,
            overlap=llm_cfg.overlap,
            chunk_strategy=llm_cfg.chunk_strategy,
        )
        doc_data = processor.process_document(options.file_path)
        document_id = Path(doc_data["filename"]).stem
        chunks = processor.chunk_text(doc_data["text"])
        if options.max_chunks and len(chunks) > options.max_chunks:
            chunks = chunks[:options.max_chunks]
        return ChunkPlan(
            document_id=document_id,
            filename=doc_data["filename"],
            word_count=doc_data["word_count"],
            chunks=chunks,
            llm_model=resolved_model,
        )

    def _extract_entities(self, ctx: _RunContext) -> EntityPassResult:
        ctx.ensure_not_cancelled()
        total_chunks = len(ctx.chunks)

        ctx.reporter.emit(ProgressEvent(
            stage="entities",
            payload={
                "kind": "pass_banner",
                "title": "Pass 1 of 2 — Entity extraction",
                "lines": [
                    f"({total_chunks} chunk(s) × {ctx.llm_cfg.chunk_size} words, "
                    f"{ctx.llm_cfg.chunk_strategy} chunking)",
                ],
            },
        ))

        all_entities: List[dict] = []
        chunk_entity_counts: List[int] = []

        def work(index: int, chunk: str) -> List[dict]:
            chunk_num = index + 1
            try:
                return ctx.entity_extractor.extract(
                    chunk,
                    progress_label=f"chunk {chunk_num}/{total_chunks} · entities",
                )
            except ExtractionError as exc:
                _emit_llm_failure(
                    ctx.reporter,
                    exc,
                    chunk_num=chunk_num,
                    total_chunks=total_chunks,
                    kind="extraction_error",
                    hints=[
                        "Set disable_thinking: true in config.yaml for thinking models",
                        "Try a different model or adjust the entity extraction prompt",
                        "Use --max-chunks 1 to isolate which chunk fails",
                    ],
                )
                raise
            except LLMError as exc:
                _emit_llm_failure(
                    ctx.reporter,
                    exc,
                    chunk_num=chunk_num,
                    total_chunks=total_chunks,
                    kind="llm_error",
                )
                raise

        def on_done(index: int, entities: List[dict], elapsed: float) -> None:
            chunk_num = index + 1
            ctx.bench.record_llm_call(
                ctx.run_id, "entity_extraction", elapsed, chunk_number=chunk_num,
            )
            all_entities.extend(entities)
            chunk_entity_counts.append(len(entities))
            ctx.reporter.emit(ProgressEvent(
                stage="entities",
                chunk=chunk_num,
                total_chunks=total_chunks,
                message=f"  ✓ Entities: {len(entities)}  ({elapsed:.1f}s)",
            ))

        _run_chunks_in_order(ctx, "entities", ctx.chunks, work, "entities", on_done)
        ctx.chunk_entity_counts = chunk_entity_counts

        unique_entities = self._dedupe_entities(all_entities)
        entities_raw = len(unique_entities)
        ctx.reporter.emit(ProgressEvent(
            stage="entities",
            message=f"\nTotal unique entities (raw): {entities_raw}",
        ))
        return EntityPassResult(
            unique_entities=unique_entities,
            entities_raw=entities_raw,
            chunk_entity_counts=chunk_entity_counts,
        )

    def _resolve_entities(
        self,
        ctx: _RunContext,
        entity_result: EntityPassResult,
    ) -> Dict[str, dict]:
        ctx.ensure_not_cancelled()
        unique_entities = dict(entity_result.unique_entities)
        entities_raw = entity_result.entities_raw

        if ctx.app_config.entity_resolution.enabled:
            ctx.reporter.emit(ProgressEvent(
                stage="resolve",
                message=(
                    f"\nRunning entity resolution "
                    f"({', '.join(ctx.app_config.entity_resolution.strategies)})..."
                ),
            ))
            t0 = time.monotonic()
            resolver = EntityResolver(ctx.app_config.entity_resolution, llm_client=None)
            resolved_list = resolver.resolve(list(unique_entities.values()))
            unique_entities = {e["entity"]: e for e in resolved_list}
            ctx.bench.record_resolution(
                ctx.run_id,
                "+".join(ctx.app_config.entity_resolution.strategies),
                entities_before=entities_raw,
                entities_after=len(unique_entities),
                elapsed_s=time.monotonic() - t0,
            )
            ctx.reporter.emit(ProgressEvent(
                stage="resolve",
                message=f"  After resolution: {len(unique_entities)} entities",
            ))
        return unique_entities

    def _canonical_lookup(self, unique_entities: Dict[str, dict]) -> Dict[str, str]:
        lookup = {canonical_match_key(name): name for name in unique_entities}
        for entity in unique_entities.values():
            for alt in entity.get("alternate_names", []):
                lookup[canonical_match_key(alt)] = entity["entity"]
        return lookup

    def _merge_triples(
        self,
        triples: List[dict],
        canonical_lookup: Dict[str, str],
        all_triples_set: set,
        all_triples: List[dict],
    ) -> int:
        new_count = 0
        for t in triples:
            subj_raw = t.get("subject", "")
            obj_raw = t.get("object", "")
            subj = canonical_lookup.get(canonical_match_key(subj_raw), subj_raw)
            obj = canonical_lookup.get(canonical_match_key(obj_raw), obj_raw)
            t = {**t, "subject": subj, "object": obj}
            key = (t["subject"], t.get("predicate", ""), t["object"])
            if key not in all_triples_set:
                all_triples_set.add(key)
                all_triples.append(t)
                new_count += 1
        return new_count

    def _extract_relationships(
        self,
        ctx: _RunContext,
        unique_entities: Dict[str, dict],
    ) -> List[dict]:
        ctx.ensure_not_cancelled()
        canonical_names = list(unique_entities.keys())
        canonical_lookup = self._canonical_lookup(unique_entities)
        total_chunks = len(ctx.chunks)

        ctx.reporter.emit(ProgressEvent(
            stage="relationships",
            payload={
                "kind": "pass_banner",
                "title": "Pass 2 of 2 — Relationship extraction  (per-chunk)",
                "lines": [],
            },
        ))

        all_triples_set: set = set()
        all_triples: List[dict] = []

        def rel_work(index: int, chunk: str) -> List[dict]:
            chunk_num = index + 1
            try:
                return ctx.relationship_extractor.extract(
                    chunk,
                    canonical_names,
                    progress_label=f"chunk {chunk_num}/{total_chunks} · relationships",
                )
            except LLMError as exc:
                _emit_llm_failure(
                    ctx.reporter,
                    exc,
                    chunk_num=chunk_num,
                    total_chunks=total_chunks,
                    kind="llm_error",
                )
                raise

        def rel_on_done(index: int, triples: List[dict], elapsed: float) -> None:
            chunk_num = index + 1
            ctx.bench.record_llm_call(
                ctx.run_id, "relationship_extraction", elapsed, chunk_number=chunk_num,
            )
            self._merge_triples(triples, canonical_lookup, all_triples_set, all_triples)
            ctx.bench.record_chunk(
                ctx.run_id,
                chunk_num,
                word_count=len(ctx.chunks[index].split()),
                entities=ctx.chunk_entity_counts[index],
                relationships=len(triples),
                elapsed_s=elapsed,
            )
            ctx.reporter.emit(ProgressEvent(
                stage="relationships",
                chunk=chunk_num,
                total_chunks=total_chunks,
                message=f"  ✓ Relationships: {len(triples)}  ({elapsed:.1f}s)",
            ))

        _run_chunks_in_order(ctx, "relationships", ctx.chunks, rel_work, "relationships", rel_on_done)

        ctx.reporter.emit(ProgressEvent(
            stage="relationships",
            message=f"\nTotal unique triples after Pass 2: {len(all_triples)}",
        ))

        all_triples = self._extract_section_relationships(
            ctx, canonical_names, canonical_lookup, all_triples_set, all_triples,
        )
        return all_triples

    def _extract_section_relationships(
        self,
        ctx: _RunContext,
        canonical_names: List[str],
        canonical_lookup: Dict[str, str],
        all_triples_set: set,
        all_triples: List[dict],
    ) -> List[dict]:
        section_size = ctx.llm_cfg.section_size
        total_chunks = len(ctx.chunks)
        sections: List[List[str]] = []
        if section_size > 1 and total_chunks > 1:
            sections = [
                ctx.chunks[i:i + section_size]
                for i in range(0, total_chunks, section_size)
            ]
            sections = [s for s in sections if len(s) > 1]

        if not (section_size > 1 and total_chunks > 1 and sections):
            return all_triples

        ctx.ensure_not_cancelled()
        ctx.reporter.emit(ProgressEvent(
            stage="sections",
            payload={
                "kind": "pass_banner",
                "title": (
                    f"Pass 2b — Cross-section relationships "
                    f"({len(sections)} section(s), {section_size} chunks each)"
                ),
                "lines": [],
            },
        ))
        triples_before_2b = len(all_triples)

        for sec_idx, section_chunks in enumerate(sections):
            ctx.ensure_not_cancelled()
            sec_num = sec_idx + 1
            parts = [section_chunks[0]]
            for chunk in section_chunks[1:]:
                words = chunk.split()
                parts.append(" ".join(words[ctx.llm_cfg.overlap:]))
            section_text = " ".join(parts)

            chunk_range = (
                f"{sec_idx * section_size + 1}–"
                f"{sec_idx * section_size + len(section_chunks)}"
            )
            ctx.reporter.emit(ProgressEvent(
                stage="sections",
                payload={
                    "kind": "section_header",
                    "title": (
                        f"Section {sec_num}/{len(sections)}  "
                        f"(chunks {chunk_range},  {len(section_text.split())} words)"
                    ),
                },
            ))
            t0 = time.monotonic()
            triples = ctx.relationship_extractor.extract(
                section_text,
                canonical_names,
                progress_label=f"section {sec_num}/{len(sections)} · relationships",
            )
            elapsed = time.monotonic() - t0
            ctx.bench.record_llm_call(
                ctx.run_id,
                "section_relationship_extraction",
                elapsed,
                chunk_number=sec_num,
            )
            new_count = self._merge_triples(
                triples, canonical_lookup, all_triples_set, all_triples,
            )
            ctx.reporter.emit(ProgressEvent(
                stage="sections",
                message=(
                    f"  ✓ Relationships: {len(triples)} found, "
                    f"{new_count} new  ({elapsed:.1f}s)"
                ),
            ))

        added = len(all_triples) - triples_before_2b
        ctx.reporter.emit(ProgressEvent(
            stage="sections",
            message=(
                f"\nPass 2b added {added} new triple(s). "
                f"Total unique triples: {len(all_triples)}"
            ),
        ))
        return all_triples

    def _write_outputs(
        self,
        ctx: _RunContext,
        all_triples: List[dict],
        unique_entities: Dict[str, dict],
        entities_raw: int,
    ) -> PipelineResult:
        ctx.ensure_not_cancelled()
        options = ctx.options
        doc_data = ctx.doc_data
        document_id = ctx.document_id
        rep = ctx.reporter

        rep.emit(ProgressEvent(
            stage="write",
            payload={"kind": "write_step", "line": "\n1. Generating knowledge graph (TTL)..."},
        ))
        output_path = self.project_root / options.output_dir
        writer = TurtleWriter(output_dir=str(output_path))
        kg_path, proposals = writer.write_knowledge_graph(
            document_id=document_id,
            triples=all_triples,
            document_metadata=doc_data,
            entities=list(unique_entities.values()),
        )
        rep.emit(ProgressEvent(
            stage="write",
            payload={"kind": "write_step", "line": f"   Knowledge graph saved to: {kg_path}"},
        ))
        if proposals:
            rep.emit(ProgressEvent(
                stage="write",
                payload={"kind": "proposals", "proposals": proposals},
            ))

        original_filename = Path(doc_data["filename"]).stem
        graph_html_filename = f"{original_filename}_graph.html"
        markup_output_path = self._artifacts.markup_path(original_filename)
        graph_output_path = self._artifacts.graph_path(original_filename)

        rep.emit(ProgressEvent(
            stage="write",
            payload={
                "kind": "write_step",
                "line": "\n2. Generating HTML markup from knowledge graph...",
            },
        ))
        markup_generator = HTMLMarkupGenerator()
        html_content = markup_generator.generate_markup_from_ttl(
            text=doc_data["text"],
            ttl_file_path=kg_path,
            document_filename=doc_data["filename"],
            graph_html_filename=graph_html_filename,
        )
        markup_path = markup_generator.save_markup(html_content, str(markup_output_path))
        rep.emit(ProgressEvent(
            stage="write",
            payload={"kind": "write_step", "line": f"   HTML markup saved to: {markup_path}"},
        ))

        graph_path = None
        if options.with_graph:
            rep.emit(ProgressEvent(
                stage="write",
                payload={"kind": "write_step", "line": "\n3. Generating graph visualisation..."},
            ))
            graph_result = self._artifacts.generate_graph_from_ttl(
                kg_path, str(graph_output_path), reporter=rep,
            )
            graph_path = graph_result.output_path

        store = MetadataStore()
        store.add_document(document_id, doc_data, kg_path)
        rep.emit(ProgressEvent(stage="write", message="Metadata updated"))

        total_elapsed = time.monotonic() - ctx.run_start
        ctx.bench.finish_run(
            ctx.run_id,
            chunk_count=len(ctx.chunks),
            entities_raw=entities_raw,
            entities_resolved=len(unique_entities),
            triples=len(all_triples),
            elapsed_s=total_elapsed,
            proposals=len(proposals),
        )
        ctx.bench.close()

        rep.emit(ProgressEvent(stage="done", message="Processing complete"))

        return PipelineResult(
            document_id=document_id,
            kg_path=kg_path,
            markup_path=markup_path,
            graph_path=graph_path,
            entity_count=len(unique_entities),
            triple_count=len(all_triples),
            proposals=proposals,
        )

    @staticmethod
    def _dedupe_entities(all_entities: List[dict]) -> dict:
        """Collapse case/spacing-variant entities into one canonical surface form.

        Variants are grouped by a case- and whitespace-insensitive key. The
        canonical form is the most frequently extracted surface form, then the
        most uppercase-rich (keeps acronyms like HDFS over Hdfs), then the
        longest. Remaining variants are kept as alternate_names so the markup
        correlator and triple merge can still link them.
        """
        groups: dict = {}
        for entity in all_entities:
            name = normalise_whitespace(entity.get("entity", ""))
            if not name:
                continue
            key = canonical_match_key(name)
            group = groups.get(key)
            if group is None:
                groups[key] = {"base": {**entity, "entity": name}, "forms": Counter()}
                group = groups[key]
            group["forms"][name] += 1
            base = group["base"]
            if base.get("type", "Other") == "Other" and entity.get("type", "Other") != "Other":
                base["type"] = entity["type"]

        def _rank(item: tuple) -> tuple:
            form, count = item
            return (count, sum(1 for c in form if c.isupper()), len(form))

        unique_entities: dict = {}
        for group in groups.values():
            forms = group["forms"]
            canonical = max(forms.items(), key=_rank)[0]
            base = group["base"]
            base["entity"] = canonical
            base["alternate_names"] = sorted(f for f in forms if f != canonical)
            unique_entities[canonical] = base
        return unique_entities
