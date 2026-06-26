"""
LLM-based ontology placement proposer.

Given an existing ontology and a new class label, asks the LLM to generate
3 ranked rdfs:subClassOf placement options with confidence scores and reasoning.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from rdflib import Graph
from rdflib.namespace import OWL, RDFS

logger = logging.getLogger(__name__)

ONT_BASE = "http://example.org/ontology/"

_SYSTEM = """\
You are an expert ontology engineer helping to place a new class into an existing OWL ontology.
Given the existing classes and a new class label, propose exactly 3 possible rdfs:subClassOf
placements ranked by confidence.

Return ONLY a JSON array — no explanation, no markdown. Each element must have:
  "parent": the parent class URI (use the exact URI from the existing ontology, or owl:Thing)
  "confidence": float 0–1
  "reasoning": one concise sentence explaining why"""

_USER = """\
Existing ontology classes:
{class_list}

New class to place: "{label}"
Source context: "{context}"

JSON array of 3 placements (no preamble):"""


class PlacementProposer:
    """Generate rdfs:subClassOf proposals using an LLM."""

    def __init__(self, llm_client):
        self._llm = llm_client

    def propose(
        self,
        label: str,
        ontology_graph: Graph,
        context: str = "",
        n: int = 3,
    ) -> List[Dict]:
        """
        Generate `n` ranked placement proposals for `label`.

        Returns list of {"parent", "confidence", "reasoning"}.
        """
        class_list = self._describe_classes(ontology_graph)
        user_prompt = _USER.format(
            class_list=class_list,
            label=label,
            context=context or "no additional context",
        )
        try:
            response = self._llm.generate(
                prompt=user_prompt,
                system_prompt=_SYSTEM,
                max_new_tokens=512,
                temperature=0.2,
                progress_label="ontology · placement proposals",
            ).text
        except Exception as e:
            logger.warning("LLM placement proposal failed: %s", e)
            return self._fallback(ontology_graph, n)

        from src.extraction.json_utils import extract_json
        data = extract_json(response, prefer="array")
        if not isinstance(data, list):
            return self._fallback(ontology_graph, n)

        proposals = []
        for item in data[:n]:
            if not isinstance(item, dict):
                continue
            parent = item.get("parent", "")
            # Normalise parent URI
            if not parent.startswith("http"):
                if ":" in parent:
                    # e.g. "ont:Technology" → full URI
                    prefix, local = parent.split(":", 1)
                    if prefix.lower() in ("ont", "ontology"):
                        parent = ONT_BASE + local.strip()
                    elif prefix.lower() == "owl":
                        parent = f"http://www.w3.org/2002/07/owl#{local.strip()}"
                    else:
                        parent = ONT_BASE + local.strip()
                else:
                    parent = ONT_BASE + parent.strip().replace(" ", "_")
            proposals.append({
                "parent": parent,
                "confidence": float(item.get("confidence", 0.5)),
                "reasoning": item.get("reasoning", ""),
            })

        # Sort by confidence descending
        proposals.sort(key=lambda x: x["confidence"], reverse=True)
        return proposals[:n] or self._fallback(ontology_graph, n)

    def _describe_classes(self, graph: Graph) -> str:
        """Build a concise list of existing classes for the prompt."""
        lines = []
        for cls in sorted(graph.subjects(None, None)):
            cls_str = str(cls)
            if not cls_str.startswith(ONT_BASE):
                continue
            label = next(graph.objects(cls, RDFS.label), None)
            comment = next(graph.objects(cls, RDFS.comment), None)
            local = cls_str.replace(ONT_BASE, "ont:")
            desc = f"  • {local}"
            if label:
                desc += f' "{label}"'
            if comment:
                desc += f" — {str(comment)[:80]}"
            lines.append(desc)
        return "\n".join(lines) if lines else "  (no existing classes)"

    def _fallback(self, graph: Graph, n: int) -> List[Dict]:
        """Return generic fallback proposals when LLM fails."""
        existing = [
            str(s) for s in graph.subjects(None, None)
            if str(s).startswith(ONT_BASE)
        ]
        proposals = []
        if existing:
            proposals.append({
                "parent": existing[0],
                "confidence": 0.5,
                "reasoning": "Fallback: place under first existing class",
            })
        proposals.append({
            "parent": "http://www.w3.org/2002/07/owl#Thing",
            "confidence": 0.3,
            "reasoning": "Fallback: top-level class with no hierarchy constraint",
        })
        return proposals[:n]
