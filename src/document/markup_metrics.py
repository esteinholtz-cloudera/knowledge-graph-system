"""Shared markup-vs-source metric helpers for entity extraction evaluation."""
from __future__ import annotations

import re


def surface_key(text: str) -> str:
    """Case-, spacing-, and underscore-insensitive key for surface-form matching."""
    return re.sub(r"[\s_]+", " ", text.strip()).casefold()


def orphan_entities(
    entities: list[tuple[str, str]], spans: list[tuple[str, str, str]]
) -> list[str]:
    """Entities listed in the sidebar but never marked inline in the document."""
    marked = {surface_key(text) for _, text, _ in spans if text}
    return sorted(name for name, _ in entities if surface_key(name) not in marked)


def verbatim_issues(entities: list[tuple[str, str]], source: str) -> list[dict]:
    """Flag entities whose surface form is absent from the source text."""
    issues = []
    norm_source = surface_key(source)
    for name, typ in entities:
        if name in source:
            continue
        if surface_key(name) in norm_source:
            issues.append({"entity": name, "type": typ, "issue": "case_or_spacing_drift"})
        elif name.lower() in source.lower():
            issues.append({"entity": name, "type": typ, "issue": "case_or_spacing_drift"})
        else:
            issues.append({"entity": name, "type": typ, "issue": "not_in_source"})
    return issues
