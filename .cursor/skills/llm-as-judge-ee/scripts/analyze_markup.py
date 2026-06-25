#!/usr/bin/env python3
"""Compute entity-extraction metrics from markup HTML vs source text."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from html import unescape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.document.markup_metrics import orphan_entities, verbatim_issues  # noqa: E402


ENTITY_LIST_RE = re.compile(
    r'<li>(?:<a[^>]*class="entity-name"[^>]*>|'
    r'<span class="entity-name">)([^<]+)(?:</a>|</span>)\s*'
    r'<span class="entity-type">\(([^)]+)\)</span></li>'
)
SPAN_RE = re.compile(
    r'<span[^>]*class="entity entity-([^"]+)"[^>]*>'
    r'(?:.*?<a[^>]*>([^<]*)</a>)'
    r'<span class="entity-badge"[^>]*>([^<]*)</span></span>',
    re.DOTALL,
)


def load_entities(html: str) -> list[tuple[str, str]]:
    return [(unescape(name), typ) for name, typ in ENTITY_LIST_RE.findall(html)]


def load_spans(html: str) -> list[tuple[str, str, str]]:
    return [(typ, unescape(text.strip()), badge.strip()) for typ, text, badge in SPAN_RE.findall(html)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markup_html", type=Path)
    parser.add_argument("source_text", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    html = args.markup_html.read_text(encoding="utf-8")
    source = args.source_text.read_text(encoding="utf-8")

    entities = load_entities(html)
    spans = load_spans(html)
    type_counts = Counter(t for _, t in entities)
    orphans = orphan_entities(entities, spans)
    verbatim = verbatim_issues(entities, source)
    span_text_counts = Counter(t for _, t, _ in spans if t)

    report = {
        "markup_html": str(args.markup_html),
        "source_text": str(args.source_text),
        "unique_entities": len(entities),
        "marked_spans": len(spans),
        "orphan_entities": len(orphans),
        "orphan_rate": round(len(orphans) / len(entities), 3) if entities else 0.0,
        "verbatim_issues": len(verbatim),
        "type_distribution_unique": dict(type_counts.most_common()),
        "orphan_entity_names": orphans[:50],
        "verbatim_issue_samples": verbatim[:30],
        "top_marked_entities": span_text_counts.most_common(15),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Unique entities: {report['unique_entities']}")
        print(f"Marked spans: {report['marked_spans']}")
        print(f"Orphan entities: {report['orphan_entities']} ({report['orphan_rate']:.0%})")
        print(f"Verbatim issues: {report['verbatim_issues']}")
        print("\nType distribution (unique):")
        for t, c in type_counts.most_common():
            print(f"  {t}: {c}")
        if orphans:
            print("\nSample orphan entities (listed but unmarked):")
            for name in orphans[:10]:
                print(f"  - {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
