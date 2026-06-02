"""Archive data/ directory and reset workspace data."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config.settings import load_config
from src.services.models import ArchiveResult

_DATA_SUBDIRS = ["documents", "knowledge_graphs", "ontology"]
_EXCLUDE = {"benchmark.duckdb", "benchmark.duckdb.wal"}
_KEEP = {"benchmark.duckdb", "benchmark.duckdb.wal"}


class ArchiveService:
    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]

    def create(self, name: Optional[str] = None, llmnamed: bool = False) -> ArchiveResult:
        if llmnamed:
            from src.extraction.providers.factory import create_provider

            cfg = load_config()
            provider = create_provider(cfg.llm)
            model_name = provider.model
            label = model_name.replace("/", "_").replace(":", "_").replace(" ", "_")
        else:
            label = name or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        src = self.project_root / "data"
        dst = self.project_root / f"data_save_{label}"

        if dst.exists():
            raise FileExistsError(f"Archive already exists: {dst}")

        def _ignore(directory, contents):
            return [c for c in contents if c in _EXCLUDE]

        shutil.copytree(src, dst, ignore=_ignore)

        paths_updated = 0
        meta_file = dst / "metadata.json"
        if meta_file.exists():
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            old_data_str = str(src.resolve())
            new_data_str = str(dst.resolve())
            for doc in data.get("documents", {}).values():
                for field in ("path", "kg_path"):
                    if field in doc and doc[field] and old_data_str in doc[field]:
                        doc[field] = doc[field].replace(old_data_str, new_data_str)
                        paths_updated += 1
            meta_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        from rdflib import Graph as RDFGraph
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import XSD

        schema_url = "http://schema.org/url"
        old_data_str = str(src.resolve())
        new_data_str = str(dst.resolve())
        ttl_updated = 0

        kg_dir = dst / "knowledge_graphs"
        if kg_dir.exists():
            for ttl_file in kg_dir.glob("*.ttl"):
                g = RDFGraph()
                g.parse(str(ttl_file), format="turtle")
                changes = []
                for s, p, o in g:
                    if str(p) == schema_url and isinstance(o, RDFLiteral) and old_data_str in str(o):
                        changes.append((s, p, o))
                for s, p, o in changes:
                    g.remove((s, p, o))
                    new_val = str(o).replace(old_data_str, new_data_str)
                    g.add((s, p, RDFLiteral(new_val, datatype=XSD.string)))
                if changes:
                    g.serialize(destination=str(ttl_file), format="turtle")
                    ttl_updated += 1

        for item in src.iterdir():
            if item.name in _KEEP:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        for subdir in _DATA_SUBDIRS:
            (src / subdir).mkdir(exist_ok=True)
        ontology_src = dst / "ontology" / "ontology.ttl"
        if ontology_src.exists():
            shutil.copy2(ontology_src, src / "ontology" / "ontology.ttl")

        return ArchiveResult(
            archive_path=str(dst),
            paths_updated=paths_updated,
            ttl_files_updated=ttl_updated,
        )
