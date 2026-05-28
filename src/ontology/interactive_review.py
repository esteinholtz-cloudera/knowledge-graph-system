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


def _print_proposals(proposals: List[Dict], wikidata_hits: Optional[List[Dict]] = None):
    """Print the numbered proposal list."""
    if wikidata_hits:
        print("\n  Wikidata matches:")
        for i, hit in enumerate(wikidata_hits[:3], 1):
            desc = hit.get("description", "")[:70]
            print(f"    {i}. {hit['qid']}  \"{hit['label']}\" — {desc}")
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

        while True:
            _print_proposals(proposals, wikidata_hits if wikidata_hits else None)

            letters = "".join(chr(ord("a") + i) for i in range(len(proposals)))
            print(f"\n  d) Try again   s) Search Wikidata   m) Specify manually   r) Reject")
            choice = input(f"\n  Choice [{letters}/d/s/m/r]: ").strip().lower()

            if choice == "r":
                store.set_status(uri, "rejected")
                store.save()
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
                print()
                for i, hit in enumerate(hits[:5], 1):
                    desc = hit.get("description", "")[:70]
                    print(f"  {i}. {hit['qid']}  \"{hit['label']}\" — {desc}")
                pick = input("\n  Pick result number (0 to cancel): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(hits):
                    selected = hits[int(pick) - 1]
                    qid = selected["qid"]
                    # Get superclasses to infer subClassOf
                    parents = _wikidata_superclasses(qid, wikidata_mode)
                    equiv_uri = f"http://www.wikidata.org/entity/{qid}"
                    store.set_equivalent_class(uri, equiv_uri)
                    print(f"  → Added owl:equivalentClass wd:{qid}")
                    if parents:
                        mapped = _map_wikidata_parents(parents, ontology)
                        if mapped:
                            store.set_subclass_of(uri, mapped)
                            store.set_status(uri, "approved")
                            store.save()
                            print(f"  → Added rdfs:subClassOf {_label_uri(mapped)}")
                            print("  → Approved.")
                            reviewed += 1
                            break
                        else:
                            print("  (Could not map Wikidata parents to ontology — choose placement manually)")
                continue

            elif choice == "m":
                raw = input("  Parent URI or 'ont:ClassName' (blank = owl:Thing): ").strip()
                if not raw:
                    parent = "http://www.w3.org/2002/07/owl#Thing"
                elif raw.startswith("ont:"):
                    parent = ONT_BASE + raw[4:]
                elif raw.startswith("http"):
                    parent = raw
                else:
                    parent = ONT_BASE + raw.replace(" ", "_")
                store.set_subclass_of(uri, parent)
                store.set_status(uri, "approved")
                store.save()
                print(f"  → rdfs:subClassOf {_label_uri(parent)}")
                print("  → Approved.")
                reviewed += 1
                break

            elif choice in letters:
                idx_choice = ord(choice) - ord("a")
                if idx_choice < len(proposals):
                    chosen = proposals[idx_choice]
                    store.set_subclass_of(uri, chosen["parent"])
                    store.set_status(uri, "approved")
                    store.save()
                    print(f"  → rdfs:subClassOf {_label_uri(chosen['parent'])}")
                    print("  → Approved.")
                    reviewed += 1
                    break
            else:
                print(f"  Invalid choice '{choice}'. Please try again.")

    print(f"\n{_DIVIDER}")
    print(f"  Review complete: {reviewed}/{total} classes processed.")
    if reviewed > 0:
        merged = store.merge_approved_into_ontology()
        if merged:
            print(f"  Merged {merged} approved class(es) into ontology.ttl")
    print(_DIVIDER)
    return reviewed


# ------------------------------------------------------------------
# Wikidata helpers (isolated so mode can be switched)
# ------------------------------------------------------------------

def _wikidata_search(term: str, mode: str) -> List[Dict]:
    if mode == "disabled":
        return []
    try:
        from .wikidata_client import WikidataClient
        with WikidataClient() as wd:
            return wd.search_entity(term)
    except Exception as e:
        print(f"  [Wikidata] search failed: {e}")
        return []


def _wikidata_superclasses(qid: str, mode: str) -> List[Dict]:
    if mode == "disabled":
        return []
    try:
        from .wikidata_client import WikidataClient
        with WikidataClient() as wd:
            return wd.get_superclasses(qid)
    except Exception as e:
        print(f"  [Wikidata] superclass lookup failed: {e}")
        return []


def _map_wikidata_parents(parents: List[Dict], ontology: Graph) -> Optional[str]:
    """
    Try to map Wikidata parent labels to an existing ontology class URI.
    Returns the best matching ontology URI or None.
    """
    ont_classes = {
        str(next(ontology.objects(s, RDFS.label), "")).lower(): str(s)
        for s in ontology.subjects(None, None)
        if str(s).startswith(ONT_BASE)
    }
    for parent in parents:
        lbl = parent.get("label", "").lower()
        for ont_label, ont_uri in ont_classes.items():
            if ont_label and (lbl in ont_label or ont_label in lbl):
                return ont_uri
    return None
