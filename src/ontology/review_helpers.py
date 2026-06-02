"""Pure helpers for ontology proposal review (no stdin/stdout)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rdflib import Graph
from rdflib.namespace import RDFS

from .placement_proposer import PlacementProposer
from .proposal_store import ONT_BASE, ProposalStore


def resolve_parent_uri(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "http://www.w3.org/2002/07/owl#Thing"
    if raw.startswith("ont:"):
        return ONT_BASE + raw[4:]
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return ONT_BASE + raw.replace(" ", "_")


def search_wikidata(term: str, mode: str = "subprocess") -> List[Dict[str, Any]]:
    if mode == "disabled":
        return []
    try:
        from .wikidata_client import WikidataClient
        with WikidataClient() as wd:
            return wd.search_entity(term)
    except Exception:
        return []


def wikidata_superclasses(qid: str, mode: str = "subprocess") -> List[Dict[str, Any]]:
    if mode == "disabled":
        return []
    try:
        from .wikidata_client import WikidataClient
        with WikidataClient() as wd:
            return wd.get_superclasses(qid)
    except Exception:
        return []


def map_wikidata_parents(parents: List[Dict], ontology: Graph) -> Optional[str]:
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


def suggest_parents(
    label: str,
    ontology: Graph,
    llm_client=None,
    context: str = "",
) -> Dict[str, Any]:
    """Return LLM placement proposals and optional Wikidata search hits."""
    app_config = None
    wikidata_mode = "subprocess"
    try:
        from src.config.settings import load_config
        app_config = load_config()
        wikidata_mode = app_config.ontology.wikidata_mcp
    except Exception:
        pass

    proposals: List[Dict] = []
    if llm_client:
        proposer = PlacementProposer(llm_client)
        proposals = proposer.propose(label, ontology, context)
    else:
        proposals = [{
            "parent": "http://www.w3.org/2002/07/owl#Thing",
            "confidence": 0.5,
            "reasoning": "No LLM available — defaulting to top-level class",
        }]

    wikidata_hits = search_wikidata(label, wikidata_mode) if wikidata_mode != "disabled" else []
    wikidata_parents: List[Dict] = []
    parent_choices: List[Dict] = []
    selected_qid: Optional[str] = None
    if wikidata_hits:
        qid = wikidata_hits[0].get("qid")
        if qid:
            wikidata_parents = wikidata_superclasses(qid, wikidata_mode)
            parent_choices = parent_choices_from_wikidata(wikidata_parents, ontology)
            selected_qid = qid

    return {
        "proposals": proposals,
        "wikidata_hits": wikidata_hits[:5],
        "wikidata_parents": wikidata_parents,
        "parent_choices": parent_choices,
        "selected_wikidata_qid": selected_qid,
    }


def apply_proposal_decision(
    store: ProposalStore,
    class_uri: str,
    status: Optional[str] = None,
    parent_class_uri: Optional[str] = None,
    wikidata_id: Optional[str] = None,
    ontology: Optional[Graph] = None,
) -> Dict[str, Any]:
    """Apply review decision to a proposed class and persist."""
    if wikidata_id:
        qid = wikidata_id if wikidata_id.startswith("http") else f"http://www.wikidata.org/entity/{wikidata_id}"
        store.set_equivalent_class(class_uri, qid)
    if parent_class_uri is not None:
        store.set_subclass_of(class_uri, resolve_parent_uri(parent_class_uri))
    elif status == "approved" and not _has_subclass(store, class_uri):
        store.set_subclass_of(class_uri, resolve_parent_uri(""))
    if status:
        store.set_status(class_uri, status)
    store.save()
    for cls in store.get_all():
        if cls["uri"] == class_uri:
            return cls
    raise KeyError(f"proposal not found: {class_uri}")


def _has_subclass(store: ProposalStore, class_uri: str) -> bool:
    for cls in store.get_all():
        if cls["uri"] == class_uri:
            return bool(cls.get("subclass_of"))
    return False


def normalize_wikidata_qid(qid: str) -> str:
    qid = (qid or "").strip()
    if qid.startswith("http://www.wikidata.org/entity/"):
        return qid.rsplit("/", 1)[-1]
    if qid.startswith("wd:"):
        return qid[3:]
    return qid


def wikidata_entity_uri(qid: str) -> str:
    return f"http://www.wikidata.org/entity/{normalize_wikidata_qid(qid)}"


def pick_wikidata_entity(
    store: ProposalStore,
    class_uri: str,
    qid: str,
    wikidata_mode: str = "subprocess",
) -> List[Dict[str, Any]]:
    """Set owl:equivalentClass for the proposal and return P279 superclass options."""
    entity_uri = wikidata_entity_uri(qid)
    store.set_equivalent_class(class_uri, entity_uri)
    store.save()
    return wikidata_superclasses(normalize_wikidata_qid(qid), wikidata_mode)


def resolve_wikidata_parent_uri(
    parent_info: Dict[str, Any],
    store: ProposalStore,
    ontology: Graph,
) -> tuple:
    """
    Map a Wikidata P279 parent to an ontology class URI.
    Returns (parent_uri, new_pending_class_dict or None).
    """
    mapped = map_wikidata_parents([parent_info], ontology)
    if mapped:
        return mapped, None

    label = parent_info["label"]
    qid = parent_info["qid"]
    new_uri = str(store.add_class(
        label=label,
        comment=f"Added via Wikidata P279 lookup (wd:{qid})",
        proposed_by=f"wd:{qid}",
        status="pending",
    ))
    store.set_equivalent_class(new_uri, wikidata_entity_uri(qid))
    new_cls = {
        "uri": new_uri,
        "label": label,
        "comment": "",
        "status": "pending",
        "proposed_by": f"wd:{qid}",
        "subclass_of": [],
        "equivalent_class": [wikidata_entity_uri(qid)],
    }
    return new_uri, new_cls


def parent_choices_from_wikidata(
    parents: List[Dict[str, Any]],
    ontology: Graph,
) -> List[Dict[str, Any]]:
    """Enrich Wikidata P279 parents with mapped ontology URIs when possible."""
    choices = []
    for p in parents:
        mapped = map_wikidata_parents([p], ontology)
        choices.append({
            "qid": p.get("qid", ""),
            "label": p.get("label", ""),
            "mapped_parent_uri": mapped,
        })
    return choices


def approve_with_wikidata_parent(
    store: ProposalStore,
    class_uri: str,
    parent_info: Dict[str, Any],
    ontology: Graph,
) -> Dict[str, Any]:
    """Place proposal under a Wikidata P279 parent and approve."""
    parent_uri, new_pending = resolve_wikidata_parent_uri(parent_info, store, ontology)
    store.set_subclass_of(class_uri, parent_uri)
    store.set_status(class_uri, "approved")
    store.save()
    proposal = None
    for cls in store.get_all():
        if cls["uri"] == class_uri:
            proposal = cls
            break
    return {
        "proposal": proposal,
        "parent_uri": parent_uri,
        "new_pending_class": new_pending,
    }
