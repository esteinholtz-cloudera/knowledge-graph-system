"""Resolve markup document links for taxonomy review entities."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from src.document.markup_anchors import (
    anchor_exists_in_html,
    document_id_from_proposal_text,
    document_id_from_source_ttl,
    entity_markup_anchor,
    entity_uri_in_markup,
    sample_entity_for_class,
    source_document_for_entity,
    source_document_for_entity_label,
)


@dataclass
class MarkupLinkResult:
    available: bool
    document_id: Optional[str] = None
    anchor: Optional[str] = None
    entity_label: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "document_id": self.document_id,
            "anchor": self.anchor,
            "entity_label": self.entity_label,
            "reason": self.reason,
        }


class MarkupLinkService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def _markup_path(self, document_id: str) -> Optional[Path]:
        path = self.project_root / "data" / "documents" / f"{document_id}_markup.html"
        return path if path.is_file() else None

    def resolve_for_proposal(
        self,
        *,
        entity_uri: Optional[str],
        entity_label: str,
        source_ttl: Optional[str],
        proposed_by: Optional[str] = None,
        class_comment: Optional[str] = None,
        leaf_class_uri: Optional[str] = None,
    ) -> MarkupLinkResult:
        label = (entity_label or "").strip()
        if not label and not entity_uri:
            return MarkupLinkResult(
                available=False,
                reason="no entity label or uri on proposal",
            )

        document_id = document_id_from_source_ttl(source_ttl or "", self.project_root)
        if not document_id:
            document_id = document_id_from_proposal_text(proposed_by, class_comment)
        if not document_id and entity_uri:
            document_id = source_document_for_entity(entity_uri, self.project_root)
        if not document_id and label:
            document_id = source_document_for_entity_label(label, self.project_root)

        if not document_id:
            return MarkupLinkResult(
                available=False,
                entity_label=label or None,
                reason="could not resolve source document",
            )

        markup_path = self._markup_path(document_id)
        if not markup_path:
            return MarkupLinkResult(
                available=False,
                document_id=document_id,
                entity_label=label or None,
                reason=f"markup not found for {document_id} — re-run the pipeline on that document",
            )

        target_uri = entity_uri
        target_label = label
        if not target_uri and leaf_class_uri:
            sample_uri, sample_label = sample_entity_for_class(
                document_id, leaf_class_uri, self.project_root,
            )
            if sample_uri:
                target_uri = sample_uri
                target_label = sample_label or target_label

        html_text = markup_path.read_text(encoding="utf-8", errors="replace")
        anchor = entity_markup_anchor(target_uri, target_label, occurrence=0)
        if anchor_exists_in_html(html_text, anchor):
            return MarkupLinkResult(
                available=True,
                document_id=document_id,
                anchor=anchor,
                entity_label=target_label or None,
            )

        if target_uri and entity_uri_in_markup(html_text, target_uri):
            return MarkupLinkResult(
                available=True,
                document_id=document_id,
                anchor=None,
                entity_label=target_label or None,
                reason="opening markup at entity link (regenerate markup for precise anchors)",
            )

        if target_label and target_label.lower() in html_text.lower():
            return MarkupLinkResult(
                available=True,
                document_id=document_id,
                anchor=None,
                entity_label=target_label,
                reason="opening markup with text search",
            )

        return MarkupLinkResult(
            available=False,
            document_id=document_id,
            entity_label=target_label or None,
            reason=f"entity not found in {document_id} markup",
        )
