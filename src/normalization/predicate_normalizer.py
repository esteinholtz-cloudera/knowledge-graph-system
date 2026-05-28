"""
Predicate normalization for knowledge graphs.

Scans all TTL files for ad-hoc kg: predicates, clusters semantically
similar ones, maps clusters to a canonical controlled vocabulary via LLM,
and optionally rewrites the TTL files.

Two-phase workflow:
  1. scan  — collects predicates, writes data/predicate_map.yaml for human review
  2. apply — reads the reviewed map, rewrites TTL files, updates ontology.ttl
             with owl:subPropertyOf declarations

Run via:
  python main.py normalize scan
  python main.py normalize apply
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS


KG = Namespace("http://example.org/kg/")
ONT = Namespace("http://example.org/ontology/")

# The canonical vocabulary that predicates should be normalised toward.
CANONICAL_PREDICATES = [
    "requires", "supports", "hasVersion", "isPartOf", "configures", "uses",
    "enables", "isCompatibleWith", "hasProperty", "replaces", "upgradesTo",
    "instanceOf", "locatedIn", "worksFor", "produces", "dependsOn",
    "manages", "references",
]

# Predicates to ignore (RDF/OWL infrastructure, not domain predicates).
_SKIP_PREDICATES = {
    "type", "label", "comment", "subClassOf", "subPropertyOf",
    "equivalentClass", "imports", "sameAs", "isDefinedBy",
    "sourceDocument", "hash", "alternateName", "scope", "strength",
    "predicate", "object", "hasQualifiedRelation",
}


def _camel_to_words(s: str) -> str:
    """Split camelCase into lowercase words: requiresHA → requires ha."""
    return re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', s).lower()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _camel_to_words(a), _camel_to_words(b)).ratio()


def scan_predicates(kg_dir: str) -> Dict[str, int]:
    """Return {predicate_local_name: count} for all kg: predicates across TTL files."""
    counts: Counter = Counter()
    for ttl in Path(kg_dir).glob("*.ttl"):
        g = Graph()
        try:
            g.parse(str(ttl), format="turtle")
        except Exception:
            continue
        for _, p, _ in g:
            local = str(p).split("/")[-1]
            if str(p).startswith(str(KG)) and local not in _SKIP_PREDICATES:
                counts[local] += 1
    return dict(counts)


def cluster_predicates(predicates: Dict[str, int], threshold: float = 0.6) -> List[List[str]]:
    """
    Group predicates by string similarity.
    Returns list of clusters (each cluster is a list of predicate local names).
    Larger clusters first.
    """
    names = list(predicates.keys())
    assigned = [False] * len(names)
    clusters = []

    for i, name in enumerate(names):
        if assigned[i]:
            continue
        cluster = [name]
        assigned[i] = True
        for j in range(i + 1, len(names)):
            if not assigned[j] and _similarity(name, names[j]) >= threshold:
                cluster.append(names[j])
                assigned[j] = True
        clusters.append(cluster)

    return sorted(clusters, key=lambda c: -sum(predicates.get(p, 0) for p in c))


def _llm_map_cluster(cluster: List[str], llm_client) -> Tuple[str, str]:
    """
    Ask the LLM to pick the best canonical predicate for a cluster.
    Returns (canonical_predicate, reasoning).
    """
    vocab = ", ".join(CANONICAL_PREDICATES)
    variants = ", ".join(cluster)
    prompt = (
        f"Given this list of predicate variants from a knowledge graph:\n"
        f"  {variants}\n\n"
        f"Choose the single best canonical predicate from this vocabulary:\n"
        f"  {vocab}\n\n"
        f"If none fit, suggest a short camelCase verb.\n"
        f'Respond with JSON: {{"canonical": "...", "reason": "..."}}'
    )
    try:
        import json
        from ..extraction.json_utils import extract_json
        response = llm_client.generate(prompt=prompt, system_prompt=None,
                                        max_new_tokens=128, temperature=0.1)
        data = extract_json(response, prefer="object")
        if isinstance(data, dict) and data.get("canonical"):
            return str(data["canonical"]).strip(), str(data.get("reason", ""))
    except Exception:
        pass
    # Fallback: pick the shortest variant as canonical
    return min(cluster, key=len), "fallback: shortest variant"


def build_predicate_map(
    kg_dir: str,
    llm_client=None,
    similarity_threshold: float = 0.6,
) -> Dict:
    """
    Scan predicates, cluster them, optionally map via LLM.
    Returns a dict suitable for writing to predicate_map.yaml.
    """
    predicates = scan_predicates(kg_dir)
    clusters = cluster_predicates(predicates, threshold=similarity_threshold)

    mapping: Dict = {"version": 1, "mappings": []}
    for cluster in clusters:
        total = sum(predicates.get(p, 0) for p in cluster)
        if llm_client and len(cluster) > 1:
            canonical, reason = _llm_map_cluster(cluster, llm_client)
        elif len(cluster) == 1:
            canonical = cluster[0]
            reason = "singleton — no mapping needed"
        else:
            canonical = min(cluster, key=len)
            reason = "no LLM — shortest variant chosen"

        mapping["mappings"].append({
            "canonical": canonical,
            "variants": cluster,
            "total_uses": total,
            "reason": reason,
            "reviewed": False,
        })

    return mapping


def apply_predicate_map(
    kg_dir: str,
    ontology_file: str,
    predicate_map: Dict,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """
    Rewrite TTL files applying the predicate mapping.
    Also appends owl:subPropertyOf declarations to ontology.ttl.

    Returns (files_rewritten, triples_remapped).
    """
    # Build flat mapping: variant → canonical
    flat: Dict[str, str] = {}
    for entry in predicate_map.get("mappings", []):
        canonical = entry["canonical"]
        for variant in entry.get("variants", []):
            if variant != canonical:
                flat[variant] = canonical

    if not flat:
        return 0, 0

    files_rewritten = 0
    triples_remapped = 0

    for ttl in Path(kg_dir).glob("*.ttl"):
        g = Graph()
        try:
            g.parse(str(ttl), format="turtle")
        except Exception:
            continue

        changes: List[Tuple] = []
        for s, p, o in g:
            local = str(p).split("/")[-1]
            if str(p).startswith(str(KG)) and local in flat:
                changes.append((s, p, o))

        if not changes:
            continue

        if not dry_run:
            for s, p, o in changes:
                local = str(p).split("/")[-1]
                canonical_uri = KG[flat[local]]
                g.remove((s, p, o))
                g.add((s, canonical_uri, o))
            g.serialize(destination=str(ttl), format="turtle")

        files_rewritten += 1
        triples_remapped += len(changes)

    # Append owl:subPropertyOf to ontology
    if not dry_run and flat:
        ont_graph = Graph()
        if Path(ontology_file).exists():
            ont_graph.parse(ontology_file, format="turtle")
        ont_graph.bind("kg", KG)
        ont_graph.bind("owl", OWL)
        for variant, canonical in flat.items():
            var_uri = KG[variant]
            can_uri = KG[canonical]
            # Only add if not already declared
            if (var_uri, OWL.subPropertyOf, can_uri) not in ont_graph:
                ont_graph.add((var_uri, RDF.type, OWL.ObjectProperty))
                ont_graph.add((var_uri, OWL.subPropertyOf, can_uri))
                ont_graph.add((can_uri, RDF.type, OWL.ObjectProperty))
        ont_graph.serialize(destination=ontology_file, format="turtle")

    return files_rewritten, triples_remapped
