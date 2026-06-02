"""Predicate normalization scan, review, and apply."""
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.services.artifacts import ArtifactService
from src.services.models import NormalizeApplyResult, NormalizeScanResult


class NormalizeService:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        artifact_service: Optional[ArtifactService] = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._artifacts = artifact_service or ArtifactService(self.project_root)

    def _default_map_path(self) -> Path:
        return self.project_root / "data" / "predicate_map.yaml"

    def get_map(self, map_file: Optional[str] = None) -> Dict[str, Any]:
        map_path = Path(map_file) if map_file else self._default_map_path()
        if not map_path.is_absolute():
            map_path = self.project_root / map_path
        if not map_path.exists():
            return {"mappings": []}
        return yaml.safe_load(map_path.read_text()) or {"mappings": []}

    def update_group(
        self,
        canonical: str,
        body: Dict[str, Any],
        map_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        from urllib.parse import unquote

        key = unquote(canonical)
        map_path = Path(map_file) if map_file else self._default_map_path()
        if not map_path.is_absolute():
            map_path = self.project_root / map_path
        if not map_path.exists():
            raise FileNotFoundError(f"No predicate map at {map_path}")

        mapping = yaml.safe_load(map_path.read_text()) or {"mappings": []}
        entries = mapping.get("mappings", [])
        match = None
        for entry in entries:
            if entry.get("canonical") == key:
                match = entry
                break
        if match is None:
            raise KeyError(f"mapping group not found: {key}")

        if "canonical" in body and body["canonical"]:
            match["canonical"] = body["canonical"]
        if "variants" in body:
            match["variants"] = body["variants"]
        if "reviewed" in body:
            match["reviewed"] = bool(body["reviewed"])

        map_path.write_text(yaml.dump(mapping, allow_unicode=True, sort_keys=False))
        return match

    def scan(
        self,
        kg_dir: str,
        map_file: str,
        no_llm: bool = False,
    ) -> NormalizeScanResult:
        from src.normalization.predicate_normalizer import build_predicate_map

        if not Path(kg_dir).is_absolute():
            kg_dir = str(self.project_root / kg_dir)

        llm_client = None
        if not no_llm:
            try:
                from src.extraction.llm_client import LLMClient
                llm_client = LLMClient.from_config()
            except Exception:
                pass

        mapping = build_predicate_map(kg_dir, llm_client=llm_client)
        n_groups = len(mapping["mappings"])
        n_review = sum(1 for m in mapping["mappings"] if len(m["variants"]) > 1)
        map_path = Path(map_file)
        if not map_path.is_absolute():
            map_path = self.project_root / map_path
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(yaml.dump(mapping, allow_unicode=True, sort_keys=False))
        return NormalizeScanResult(
            map_path=str(map_path),
            group_count=n_groups,
            review_count=n_review,
        )

    def apply(
        self,
        kg_dir: str,
        ontology_file: str,
        map_file: str,
        dry_run: bool = False,
    ) -> NormalizeApplyResult:
        from src.normalization.predicate_normalizer import apply_predicate_map

        if not Path(kg_dir).is_absolute():
            kg_dir = str(self.project_root / kg_dir)
        if not Path(ontology_file).is_absolute():
            ontology_file = str(self.project_root / ontology_file)
        map_path = Path(map_file)
        if not map_path.is_absolute():
            map_path = self.project_root / map_path
        if not map_path.exists():
            raise FileNotFoundError(f"No predicate map at {map_path}. Run 'normalize scan' first.")

        mapping = yaml.safe_load(map_path.read_text())
        reviewed = [m for m in mapping.get("mappings", []) if m.get("reviewed")]
        if not reviewed:
            raise ValueError("No mappings marked 'reviewed: true'. Edit the map file first.")

        files, triples = apply_predicate_map(
            kg_dir=kg_dir,
            ontology_file=ontology_file,
            predicate_map={"mappings": reviewed},
            dry_run=dry_run,
        )
        if not dry_run and files:
            self.regenerate_graphs(kg_dir)
        return NormalizeApplyResult(files=files, triples=triples, dry_run=dry_run)

    def run_interactive_review(self, map_file: str) -> None:
        from src.normalization._review import interactive_review
        interactive_review(map_file)

    def regenerate_graphs(self, kg_dir: str) -> int:
        docs_dir = self.project_root / "data" / "documents"
        rewritten = 0
        for ttl in sorted(Path(kg_dir).glob("*.ttl")):
            stem = ttl.stem
            html_path = docs_dir / f"{stem}_graph.html"
            if not html_path.exists():
                continue
            result = self._artifacts.generate_graph_from_ttl(str(ttl), str(html_path))
            if result.output_path:
                rewritten += 1
        return rewritten
