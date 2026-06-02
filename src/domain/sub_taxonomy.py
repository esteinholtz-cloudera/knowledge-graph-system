"""SubTaxonomyProposal domain types (transient review bundles)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ProposedClass:
    uri: str
    label: str
    comment: str = ""
    subclass_of: List[str] = field(default_factory=list)
    equivalent_class: List[str] = field(default_factory=list)
    is_new_root: bool = False
    status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uri": self.uri,
            "label": self.label,
            "comment": self.comment,
            "subclass_of": list(self.subclass_of),
            "equivalent_class": list(self.equivalent_class),
            "is_new_root": self.is_new_root,
            "status": self.status,
        }

    @classmethod
    def from_class_dict(cls, data: Dict[str, Any]) -> "ProposedClass":
        return cls(
            uri=data.get("uri", ""),
            label=data.get("label", ""),
            comment=data.get("comment", ""),
            subclass_of=list(data.get("subclass_of") or []),
            equivalent_class=list(data.get("equivalent_class") or []),
            is_new_root=bool(data.get("is_new_root", False)),
            status=data.get("status", "pending"),
        )


@dataclass
class SubclassLink:
    child_uri: str
    parent_uri: str
    source: str = "manual"

    def to_dict(self) -> Dict[str, str]:
        return {
            "child_uri": self.child_uri,
            "parent_uri": self.parent_uri,
            "source": self.source,
        }


@dataclass
class SubTaxonomyProposal:
    id: str
    status: str = "pending"
    proposed_classes: List[ProposedClass] = field(default_factory=list)
    subclass_links: List[SubclassLink] = field(default_factory=list)
    leaf_class_uri: str = ""
    entity_uri: Optional[str] = None
    source_ttl: Optional[str] = None
    proposed_by: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "label": self.label,
            "is_needs_typing": self.is_needs_typing,
            "proposed_classes": [c.to_dict() for c in self.proposed_classes],
            "subclass_links": [link.to_dict() for link in self.subclass_links],
            "leaf_class_uri": self.leaf_class_uri,
            "entity_uri": self.entity_uri,
            "source_ttl": self.source_ttl,
            "proposed_by": self.proposed_by,
            "created_at": self.created_at,
        }

    @property
    def is_needs_typing(self) -> bool:
        return bool(self.entity_uri)

    @property
    def label(self) -> str:
        if self.leaf_class_uri:
            for cls in self.proposed_classes:
                if cls.uri == self.leaf_class_uri:
                    return cls.label
        if self.proposed_classes:
            return self.proposed_classes[0].label
        return self.id


@dataclass
class SubTaxonomyApprovalResult:
    action: str
    proposal_id: str
    merged_classes: int = 0
    entity_retyped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "proposal_id": self.proposal_id,
            "merged_classes": self.merged_classes,
            "entity_retyped": self.entity_retyped,
        }
