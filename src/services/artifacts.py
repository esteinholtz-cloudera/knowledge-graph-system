"""Artifact path helpers and graph HTML generation."""
import subprocess
from pathlib import Path
from typing import Optional

from src.config.settings import load_config
from src.services.models import GraphGenerationResult
from src.services.progress import CliProgressReporter, ProgressEvent, ProgressReporter


class ArtifactService:
    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]

    def markup_path(self, document_stem: str) -> Path:
        return self.project_root / "data" / "documents" / f"{document_stem}_markup.html"

    def graph_path(self, document_stem: str) -> Path:
        return self.project_root / "data" / "documents" / f"{document_stem}_graph.html"

    def generate_graph_from_ttl(
        self,
        ttl_path: str,
        graph_html_path: str,
        reporter: Optional[ProgressReporter] = None,
    ) -> GraphGenerationResult:
        rep = reporter or CliProgressReporter()
        app_config = load_config()
        ai_kg_path = app_config.visualization.resolved_ai_kg_path()
        if not ai_kg_path:
            line = (
                "  ✗ Graph skipped — ai-knowledge-graph not found. "
                "Set visualization.ai_kg_path in config.yaml"
            )
            rep.emit(ProgressEvent(
                stage="write",
                payload={"kind": "graph_generation", "subkind": "skip", "line": line},
            ))
            return GraphGenerationResult(output_path=None)

        script = Path(ai_kg_path) / "ttl_to_html.py"
        python = Path(ai_kg_path) / ".venv" / "bin" / "python"
        if not python.exists():
            python = Path("python3")

        rep.emit(ProgressEvent(
            stage="write",
            payload={"kind": "graph_generation", "subkind": "start"},
        ))
        result = subprocess.run(
            [str(python), str(script), ttl_path, graph_html_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            rep.emit(ProgressEvent(
                stage="error",
                payload={
                    "kind": "graph_generation",
                    "subkind": "failed",
                    "stderr": result.stderr,
                },
            ))
            return GraphGenerationResult(
                output_path=None,
                stderr=result.stderr or "",
            )

        stats_lines = []
        for line in result.stdout.splitlines():
            if "Nodes:" in line or "Edges:" in line or "Communities:" in line:
                stats_lines.append(line.strip())
                rep.emit(ProgressEvent(
                    stage="write",
                    payload={"kind": "graph_generation", "subkind": "stats", "line": line},
                ))

        rep.emit(ProgressEvent(
            stage="write",
            payload={
                "kind": "graph_generation",
                "subkind": "saved",
                "path": graph_html_path,
            },
        ))
        return GraphGenerationResult(
            output_path=graph_html_path,
            stdout_lines=stats_lines,
        )
