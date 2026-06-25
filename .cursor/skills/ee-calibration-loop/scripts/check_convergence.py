#!/usr/bin/env python3
"""Check whether EE markup metrics meet convergence thresholds."""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

DEFAULT_THRESHOLDS = {
    "max_orphan_rate": 0.10,
    "max_verbatim_rate": 0.05,
    "max_other_rate": 0.10,
    "max_generic_hit_rate": 0.03,
    "max_error_score": 0.12,
    "min_grade_score": 85.0,
    "min_error_score_delta": 0.02,
}

GENERIC_BLOCKLIST = frozenset({
    "restart",
    "topic",
    "read-only",
    "follower replica",
    "leader replica",
    "external clients",
    "source cluster",
    "client configurations",
    "migration of metrics",
    "service role types",
    "kafka topics",
})

PIPELINE_ARTIFACT_TYPES = frozenset({"QualifiedRelation"})

ENTITY_LIST_RE = re.compile(
    r'<li>(?:<a[^>]*class="entity-name"[^>]*>|'
    r'<span class="entity-name">)([^<]+)(?:</a>|</span>)\s*'
    r'<span class="entity-type">\(([^)]+)\)</span></li>'
)


def load_entity_names(markup_html: Path) -> list[tuple[str, str]]:
    html = markup_html.read_text(encoding="utf-8")
    return [(unescape(name), typ) for name, typ in ENTITY_LIST_RE.findall(html)]


def compute_rates(metrics: dict, entities: list[tuple[str, str]] | None) -> dict[str, float]:
    unique = max(int(metrics.get("unique_entities", 0)), 1)
    type_dist = metrics.get("type_distribution_unique", {})
    other_count = int(type_dist.get("Other", 0))

    generic_hits = 0
    if entities:
        for name, _ in entities:
            if name.lower() in GENERIC_BLOCKLIST:
                generic_hits += 1

    orphan_rate = float(metrics.get("orphan_rate", 0.0))
    verbatim_rate = float(metrics.get("verbatim_issues", 0)) / unique
    other_rate = other_count / unique
    generic_hit_rate = generic_hits / unique

    error_score = round(
        0.30 * orphan_rate
        + 0.30 * verbatim_rate
        + 0.20 * other_rate
        + 0.20 * generic_hit_rate,
        4,
    )

    return {
        "orphan_rate": round(orphan_rate, 4),
        "verbatim_rate": round(verbatim_rate, 4),
        "other_rate": round(other_rate, 4),
        "generic_hit_rate": round(generic_hit_rate, 4),
        "error_score": error_score,
    }


def gate_results(rates: dict, thresholds: dict, grade_score: float | None) -> dict[str, bool]:
    gates = {
        "orphan_rate": rates["orphan_rate"] <= thresholds["max_orphan_rate"],
        "verbatim_rate": rates["verbatim_rate"] <= thresholds["max_verbatim_rate"],
        "other_rate": rates["other_rate"] <= thresholds["max_other_rate"],
        "generic_hit_rate": rates["generic_hit_rate"] <= thresholds["max_generic_hit_rate"],
        "error_score": rates["error_score"] <= thresholds["max_error_score"],
    }
    if grade_score is not None:
        gates["grade_score"] = grade_score >= thresholds["min_grade_score"]
    return gates


def plateau(previous: dict | None, current: dict, thresholds: dict) -> bool:
    if not previous:
        return False
    prev_score = float(previous.get("error_score", 1.0))
    delta = prev_score - float(current.get("error_score", 0.0))
    return delta < thresholds["min_error_score_delta"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-file", required=True, type=Path)
    parser.add_argument("--markup", type=Path, help="Markup HTML for generic-hit detection")
    parser.add_argument("--previous-metrics-file", type=Path)
    parser.add_argument("--grade-score", type=float, default=None)
    parser.add_argument("--thresholds-file", type=Path)
    args = parser.parse_args()

    metrics = json.loads(args.metrics_file.read_text(encoding="utf-8"))
    thresholds = DEFAULT_THRESHOLDS.copy()
    if args.thresholds_file and args.thresholds_file.is_file():
        thresholds.update(json.loads(args.thresholds_file.read_text(encoding="utf-8")))

    entities = load_entity_names(args.markup) if args.markup else None
    rates = compute_rates(metrics, entities)
    gates = gate_results(rates, thresholds, args.grade_score)

    previous_rates = None
    if args.previous_metrics_file and args.previous_metrics_file.is_file():
        prev_metrics = json.loads(args.previous_metrics_file.read_text(encoding="utf-8"))
        previous_rates = compute_rates(prev_metrics, None)

    converged = all(gates.values())
    stalled = plateau(previous_rates, rates, thresholds)

    report = {
        "converged": converged,
        "stalled": stalled,
        "rates": rates,
        "gates": gates,
        "thresholds": thresholds,
        "failed_gates": [name for name, ok in gates.items() if not ok],
        "grade_score": args.grade_score,
    }
    print(json.dumps(report, indent=2))
    return 0 if converged else 1


if __name__ == "__main__":
    sys.exit(main())
