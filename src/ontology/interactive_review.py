"""
Interactive terminal review of proposed ontology classes.

For each pending class the user chooses:
  a/b/c  — accept one of 3 LLM-ranked rdfs:subClassOf placements
  d      — try again (re-generate proposals)
  s      — search Wikidata by name
  m      — specify manually (raw parent URI or Turtle snippet)
  r      — reject (skip this class)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

from rdflib import Graph
from rdflib.namespace import OWL, RDFS

from .placement_proposer import PlacementProposer
from .proposal_store import ONT_BASE, ProposalStore
from .review_helpers import (
    apply_proposal_decision,
    approve_with_wikidata_parent,
    map_wikidata_parents as _map_wikidata_parents,
    pick_wikidata_entity,
    resolve_parent_uri,
    search_wikidata,
    wikidata_superclasses,
)

_DIVIDER = "═" * 52


def _label_uri(uri: str) -> str:
    """Return a short display form of a URI."""
    if uri.startswith(ONT_BASE):
        return "ont:" + uri[len(ONT_BASE):]
    if "owl#" in uri:
        return "owl:" + uri.split("owl#")[-1]
    if "wikidata.org/entity/" in uri:
        return "wd:" + uri.split("/")[-1]
    return uri


def _print_proposals(
    proposals: List[Dict],
    wikidata_hits: Optional[List[Dict]] = None,
    wikidata_parents: Optional[List[Dict]] = None,
):
    """Print LLM proposals and, when available, Wikidata P279 parent options."""
    if wikidata_hits:
        print("\n  Wikidata matches:")
        for i, hit in enumerate(wikidata_hits[:3], 1):
            desc = hit.get("description", "")[:70]
            print(f"    {i}. {hit['qid']}  \"{hit['label']}\" — {desc}")
        print()

    if wikidata_parents:
        print("  Wikidata P279 superclass options (use 'w' to select):\n")
        for i, p in enumerate(wikidata_parents, 1):
            print(f"    {i}. wd:{p['qid']}  \"{p['label']}\"")
        print()

    print("  LLM placement proposals (ranked by confidence):\n")
    for i, p in enumerate(proposals):
        letter = chr(ord("a") + i)
        pct = int(p["confidence"] * 100)
        parent = _label_uri(p["parent"])
        print(f"  {letter}) [{pct:3d}%]  rdfs:subClassOf {parent}")
        print(f"           {p['reasoning']}")
        if i < len(proposals) - 1:
            print()


def _print_wd_hits(hits: List[Dict]):
    print()
    for i, hit in enumerate(hits[:5], 1):
        desc = hit.get("description", "")[:70]
        print(f"  {i}. {hit['qid']}  \"{hit['label']}\" — {desc}")


def _pick_wd_result(pick: str, hits: List[Dict], uri: str, store, wikidata_mode: str) -> List[Dict]:
    """Handle a numbered pick from a Wikidata search result list."""
    if not (pick.isdigit() and 1 <= int(pick) <= len(hits)):
        return []
    selected = hits[int(pick) - 1]
    qid = selected["qid"]
    parents = pick_wikidata_entity(store, uri, qid, wikidata_mode)
    print(f"  → Added owl:equivalentClass wd:{qid}")
    if parents:
        print(f"  P279 chain: " + " → ".join(f"\"{p['label']}\"" for p in parents))
        print("  (use 'w' to place under a Wikidata parent, or choose a/b/c/m)")
    else:
        print("  (No P279 superclasses found — use 'p' to pick a different result, or a/b/c/m)")
    return parents


def run_interactive_review(
    proposal_file: str,
    ontology_file: str,
    llm_client=None,
    wikidata_mode: str = "subprocess",
) -> int:
    """
    Run the interactive review loop.

    Args:
        proposal_file: Path to ontology_proposed.ttl
        ontology_file: Path to ontology.ttl
        llm_client: LLMClient instance (None = no LLM proposals)
        wikidata_mode: "subprocess" | "disabled"

    Returns:
        Number of classes reviewed (approved + rejected).
    """
    store = ProposalStore(proposal_file, ontology_file)
    pending = store.get_pending()

    if not pending:
        print("No pending ontology proposals to review.")
        return 0

    ontology = Graph()
    if Path(ontology_file).exists():
        ontology.parse(str(ontology_file), format="turtle")

    proposer = PlacementProposer(llm_client) if llm_client else None
    reviewed = 0
    total = len(pending)

    for idx, cls in enumerate(pending, 1):
        label = cls["label"]
        context = cls.get("comment", "")
        uri = cls["uri"]

        print(f"\n{_DIVIDER}")
        print(f"  {idx}/{total}  {_label_uri(uri)}")
        if cls.get("proposed_by"):
            print(f"  Source: {cls['proposed_by']}")
        if context:
            print(f"  Context: {context[:100]}")
        print(_DIVIDER)

        proposals: List[Dict] = []
        wikidata_hits: List[Dict] = []

        # Generate LLM proposals
        if proposer:
            sys.stderr.write("  Generating LLM proposals... ")
            proposals = proposer.propose(label, ontology, context)
            sys.stderr.write("done\n")
        else:
            proposals = [
                {"parent": "http://www.w3.org/2002/07/owl#Thing", "confidence": 0.5,
                 "reasoning": "No LLM available — defaulting to top-level class"},
            ]

        wikidata_parents: List[Dict] = []

        while True:
            _print_proposals(proposals, wikidata_hits or None, wikidata_parents or None)

            letters = "".join(chr(ord("a") + i) for i in range(len(proposals)))
            wd_hint = "/w" if wikidata_parents else ""
            p_hint  = "/p" if wikidata_hits else ""
            extras = (
                ("   w) Accept Wikidata parent" if wikidata_parents else "") +
                ("   p) Re-pick from last search" if wikidata_hits else "")
            )
            print(f"\n  d) Try again   s) Search Wikidata{extras}   m) Specify manually   r) Reject")
            choice = input(f"\n  Choice [{letters}{wd_hint}{p_hint}/d/s/m/r]: ").strip().lower()

            if choice == "r":
                apply_proposal_decision(store, uri, status="rejected")
                print("  → Rejected.")
                reviewed += 1
                break

            elif choice == "d":
                if proposer:
                    sys.stderr.write("  Re-generating proposals... ")
                    proposals = proposer.propose(label, ontology, context)
                    sys.stderr.write("done\n")
                else:
                    print("  (No LLM available for re-generation)")
                continue

            elif choice == "s":
                term = input("  Search term (Enter to use class label): ").strip() or label
                print(f"  Searching Wikidata for '{term}'...")
                hits = _wikidata_search(term, wikidata_mode)
                if not hits:
                    print("  No results found.")
                    continue
                wikidata_hits = hits
                wikidata_parents = []
                _print_wd_hits(hits)
                pick = input("\n  Pick result number (0 to cancel): ").strip()
                wikidata_parents = _pick_wd_result(pick, hits, uri, store, wikidata_mode)
                continue

            elif choice == "p" and wikidata_hits:
                _print_wd_hits(wikidata_hits)
                pick = input("\n  Pick result number (0 to cancel): ").strip()
                wikidata_parents = _pick_wd_result(pick, wikidata_hits, uri, store, wikidata_mode)
                continue

            elif choice == "w" and wikidata_parents:
                pick = input(f"  Pick Wikidata parent (1–{len(wikidata_parents)}): ").strip()
                if not (pick.isdigit() and 1 <= int(pick) <= len(wikidata_parents)):
                    print("  Invalid choice.")
                    continue
                parent_info = wikidata_parents[int(pick) - 1]
                result = approve_with_wikidata_parent(store, uri, parent_info, ontology)
                parent_uri = result["parent_uri"]
                new_cls = result.get("new_pending_class")
                print(f"  → rdfs:subClassOf {_label_uri(parent_uri)}")
                print("  → Approved.")
                reviewed += 1
                if new_cls:
                    # Parent class doesn't exist in ontology yet — add to review queue
                    pending.append(new_cls)
                    total = len(pending)
                    print(f"  (ont:{parent_info['label'].title().replace(' ','_')} queued for placement — {total - idx} remaining)")
                break

            elif choice == "m":
                raw = input("  Parent URI or 'ont:ClassName' (blank = owl:Thing): ").strip()
                parent = resolve_parent_uri(raw)
                apply_proposal_decision(
                    store, uri, status="approved", parent_class_uri=raw or "owl:Thing",
                )
                print(f"  → rdfs:subClassOf {_label_uri(parent)}")
                print("  → Approved.")
                reviewed += 1
                break

            elif choice in letters:
                idx_choice = ord(choice) - ord("a")
                if idx_choice < len(proposals):
                    chosen = proposals[idx_choice]
                    apply_proposal_decision(
                        store, uri, status="approved", parent_class_uri=chosen["parent"],
                    )
                    print(f"  → rdfs:subClassOf {_label_uri(chosen['parent'])}")
                    print("  → Approved.")
                    reviewed += 1
                    break
            else:
                print(f"  Invalid choice '{choice}'. Please try again.")

    # ── Entity re-typing section ───────────────────────────────────────
    needs_typing = store.get_needs_typing()
    if needs_typing:
        print(f"\n{_DIVIDER}")
        print(f"  Entity re-typing ({len(needs_typing)} entities currently typed as ont:Other)")
        print(_DIVIDER)
        reviewed += _review_entity_retyping(needs_typing, store, ontology, proposer, wikidata_mode)

    print(f"\n{_DIVIDER}")
    print(f"  Review complete: {reviewed} item(s) processed.")
    if reviewed > 0:
        merged = store.merge_approved_into_ontology()
        if merged:
            print(f"  Merged {merged} approved class(es) into ontology.ttl")
    store.save()
    print(_DIVIDER)
    return reviewed


def _review_entity_retyping(
    needs_typing: list,
    store,
    ontology,
    proposer,
    wikidata_mode: str,
) -> int:
    """Review entities currently typed as ont:Other and assign a proper class."""
    from rdflib import Graph
    from .proposal_store import ONT_BASE

    # Build list of available ontology classes for user display
    ont_classes = sorted(
        str(s).replace(ONT_BASE, "ont:")
        for s in ontology.subjects(None, None)
        if str(s).startswith(ONT_BASE)
    )

    reviewed = 0
    total = len(needs_typing)

    for idx, entry in enumerate(needs_typing, 1):
        label = entry["label"]
        entity_uri = entry["entity_uri"]
        source_ttl = entry["source_ttl"]
        node_uri = entry["node"]

        print(f"\n  {idx}/{total}  {label}")
        print(f"  URI: {entity_uri}")
        print(f"  KG file: {source_ttl}")
        print(f"\n  Available classes: {', '.join(ont_classes[:12])}")
        if len(ont_classes) > 12:
            print(f"  ... and {len(ont_classes) - 12} more")

        # Generate LLM proposals for this entity
        proposals: list = []
        if proposer:
            proposals = proposer.propose(label, ontology, context=f"entity in knowledge graph: {label}")

        wikidata_hits: list = []

        while True:
            if proposals:
                print()
                _print_proposals(proposals, wikidata_hits if wikidata_hits else None)
            letters = "".join(chr(ord("a") + i) for i in range(len(proposals)))
            print(f"\n  d) Try again   s) Search Wikidata   m) Specify class   r) Skip")
            choice = input(f"  Choice [{letters}/d/s/m/r]: ").strip().lower()

            if choice == "r":
                print("  → Skipped.")
                reviewed += 1
                break

            elif choice == "d" and proposer:
                proposals = proposer.propose(label, ontology, context=label)
                continue

            elif choice == "s":
                term = input("  Search term (Enter to use entity label): ").strip() or label
                hits = _wikidata_search(term, wikidata_mode)
                if not hits:
                    print("  No results found.")
                    continue
                wikidata_hits = hits
                for i, hit in enumerate(hits[:5], 1):
                    desc = hit.get("description", "")[:70]
                    print(f"  {i}. {hit['qid']}  \"{hit['label']}\" — {desc}")
                pick = input("\n  Pick result (0 to cancel): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(hits):
                    selected = hits[int(pick) - 1]
                    qid = selected["qid"]
                    parents = _wikidata_superclasses(qid, wikidata_mode)
                    mapped = _map_wikidata_parents(parents, ontology)
                    if mapped:
                        store.resolve_entity_retyping(node_uri, mapped, source_ttl)
                        store.set_equivalent_class(node_uri, f"http://www.wikidata.org/entity/{qid}")
                        store.save()
                        print(f"  → Retyped to {_label_uri(mapped)}")
                        reviewed += 1
                        break
                    else:
                        print("  (Could not map to ontology class — use 'm' to specify manually)")
                continue

            elif choice == "m":
                raw = input("  Class (e.g. ont:Technology or full URI): ").strip()
                if raw.startswith("ont:"):
                    class_uri = ONT_BASE + raw[4:]
                elif raw.startswith("http"):
                    class_uri = raw
                else:
                    class_uri = ONT_BASE + raw.replace(" ", "_")
                store.resolve_entity_retyping(node_uri, class_uri, source_ttl)
                store.save()
                print(f"  → Retyped to {_label_uri(class_uri)}")
                reviewed += 1
                break

            elif choice in letters:
                idx_choice = ord(choice) - ord("a")
                if idx_choice < len(proposals):
                    chosen = proposals[idx_choice]
                    store.resolve_entity_retyping(node_uri, chosen["parent"], source_ttl)
                    store.save()
                    print(f"  → Retyped to {_label_uri(chosen['parent'])}")
                    reviewed += 1
                    break
            else:
                print(f"  Invalid choice. Try again.")

    return reviewed


def _wikidata_search(term: str, mode: str) -> List[Dict]:
    hits = search_wikidata(term, mode)
    if not hits and mode != "disabled":
        print(f"  [Wikidata] no results for '{term}'")
    return hits


def _wikidata_superclasses(qid: str, mode: str) -> List[Dict]:
    parents = wikidata_superclasses(qid, mode)
    if not parents and mode != "disabled":
        print(f"  [Wikidata] superclass lookup failed for {qid}")
    return parents
