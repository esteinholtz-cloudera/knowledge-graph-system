"""Build and approve SubTaxonomyProposal bundles from ProposalStore."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from rdflib import Graph
from rdflib.namespace import OWL, RDF

from src.domain.sub_taxonomy import (
    ProposedClass,
    SubTaxonomyApprovalResult,
    SubTaxonomyProposal,
    SubclassLink,
)
from src.ontology.proposal_store import ONT_BASE, ProposalStore
from src.ontology.review_helpers import (
    approve_with_wikidata_parent,
    normalize_wikidata_qid,
    resolve_parent_uri,
    wikidata_entity_uri,
)

logger = logging.getLogger(__name__)


def _subclass_links_for_classes(
    classes: List[ProposedClass],
    ontology_uris: set[str],
) -> List[SubclassLink]:
    links: List[SubclassLink] = []
    seen: set[tuple[str, str]] = set()
    class_uris = {c.uri for c in classes}
    for cls in classes:
        for parent in cls.subclass_of:
            key = (cls.uri, parent)
            if key in seen:
                continue
            seen.add(key)
            if parent in class_uris or parent in ontology_uris:
                links.append(SubclassLink(child_uri=cls.uri, parent_uri=parent, source="stored"))
    return links


def _ensure_bundle_ids(store: ProposalStore) -> None:
    """Assign a SubTaxonomyProposal id to each pending class and needs_typing node."""
    changed = False
    already = store._ontology_class_uris()

    for cls in store.get_all():
        if cls.get("status") != "pending" or cls["uri"] in already:
            continue
        if not store.get_sub_taxonomy_id(cls["uri"]):
            store.set_sub_taxonomy_id(cls["uri"], str(uuid.uuid4()))
            changed = True

    for entry in store.get_needs_typing():
        node = entry["node"]
        if store.get_sub_taxonomy_id(node):
            _ensure_retyping_leaf(store, entry)
            continue
        proposal_id = str(uuid.uuid4())
        store.set_sub_taxonomy_id(node, proposal_id)
        _ensure_retyping_leaf(store, entry, proposal_id=proposal_id)
        changed = True

    if changed:
        store.save()


def _ensure_retyping_leaf(
    store: ProposalStore,
    entry: Dict[str, Any],
    proposal_id: Optional[str] = None,
) -> None:
    """Ensure a needs_typing bundle has a leaf ProposedClass for the entity label."""
    node = entry["node"]
    proposal_id = proposal_id or store.get_sub_taxonomy_id(node)
    if not proposal_id:
        return
    leaf = store.get_leaf_class_uri(node)
    if leaf and store.get_sub_taxonomy_id(leaf) == proposal_id:
        return
    label = entry.get("label") or "Unknown"
    uri = str(store.add_class(
        label,
        comment=f"Retyping proposal for {entry.get('entity_uri', '')}",
        proposed_by=entry.get("proposed_by", ""),
        status="pending",
    ))
    store.set_sub_taxonomy_id(uri, proposal_id)
    store.set_leaf_class_uri(node, uri)
    store.save()


def _bundle_class_uris(store: ProposalStore, proposal_id: str) -> set[str]:
    return {
        s for s in store.subjects_for_sub_taxonomy(proposal_id)
        if s.startswith(ONT_BASE) and not s.startswith(f"{ONT_BASE}meta/")
    }


def _collect_classes_for_bundle(
    store: ProposalStore,
    proposal_id: str,
    already: set[str],
    *,
    pending_only: bool = True,
) -> List[ProposedClass]:
    uris = _bundle_class_uris(store, proposal_id)
    classes: List[ProposedClass] = []
    for cls in store.get_all():
        if cls["uri"] not in uris or cls["uri"] in already:
            continue
        status = cls.get("status")
        if pending_only:
            if status != "pending":
                continue
        elif status not in ("pending", "approved"):
            continue
        classes.append(ProposedClass.from_class_dict(cls))
    return classes


def _retype_entry_for_bundle(
    store: ProposalStore,
    proposal_id: str,
) -> Optional[Dict[str, Any]]:
    retype_node = store.get_retype_node_for_bundle(proposal_id)
    if not retype_node:
        return None
    for entry in store.get_needs_typing():
        if entry["node"] == retype_node:
            return entry
    from rdflib import URIRef

    from src.ontology.proposal_store import ENTITY_LABEL, ONT_META, PROPOSED_BY, SOURCE_TTL

    node = URIRef(retype_node)
    entity_uri = str(next(store._graph.objects(node, ONT_META.entityURI), ""))
    if not entity_uri:
        return None
    return {
        "node": retype_node,
        "entity_uri": entity_uri,
        "label": str(next(store._graph.objects(node, ENTITY_LABEL), "")),
        "source_ttl": str(next(store._graph.objects(node, SOURCE_TTL), "")),
        "proposed_by": str(next(store._graph.objects(node, PROPOSED_BY), "")),
    }


def _build_bundle(
    store: ProposalStore,
    proposal_id: str,
    retype_entry: Optional[Dict[str, Any]],
    classes: List[ProposedClass],
    ontology_uris: set[str],
) -> SubTaxonomyProposal:
    leaf = ""
    entity_uri = None
    source_ttl = None
    proposed_by = ""

    if retype_entry:
        node = retype_entry["node"]
        leaf = store.get_leaf_class_uri(node) or ""
        entity_uri = retype_entry.get("entity_uri")
        source_ttl = retype_entry.get("source_ttl")
        proposed_by = retype_entry.get("proposed_by", "")

    if not leaf and classes:
        leaf = classes[0].uri
        proposed_by = proposed_by or next(
            (c.comment for c in classes if c.uri == leaf), "",
        )

    links = _subclass_links_for_classes(classes, ontology_uris)
    return SubTaxonomyProposal(
        id=proposal_id,
        status="pending",
        proposed_classes=classes,
        subclass_links=links,
        leaf_class_uri=leaf,
        entity_uri=entity_uri,
        source_ttl=source_ttl,
        proposed_by=proposed_by,
    )


def list_sub_taxonomy_proposals(store: ProposalStore) -> List[SubTaxonomyProposal]:
    _ensure_bundle_ids(store)
    already = store._ontology_class_uris()
    ontology_uris = already | {
        "http://www.w3.org/2002/07/owl#Thing",
    }

    retype_by_id: Dict[str, Dict[str, Any]] = {}
    for entry in store.get_needs_typing():
        bid = store.get_sub_taxonomy_id(entry["node"])
        if bid:
            retype_by_id[bid] = entry

    bundle_ids: set[str] = set()
    for cls in store.get_pending():
        bid = store.get_sub_taxonomy_id(cls["uri"])
        if bid:
            bundle_ids.add(bid)
    bundle_ids.update(retype_by_id.keys())

    bundles: List[SubTaxonomyProposal] = []
    for proposal_id in sorted(bundle_ids):
        classes = _collect_classes_for_bundle(store, proposal_id, already)
        retype = retype_by_id.get(proposal_id)
        if not classes and not retype:
            continue
        bundles.append(_build_bundle(store, proposal_id, retype, classes, ontology_uris))
    return bundles


def get_sub_taxonomy_proposal(
    store: ProposalStore,
    proposal_id: str,
) -> Optional[SubTaxonomyProposal]:
    _ensure_bundle_ids(store)
    if not store.subjects_for_sub_taxonomy(proposal_id):
        return None

    already = store._ontology_class_uris()
    ontology_uris = already | {"http://www.w3.org/2002/07/owl#Thing"}
    retype = _retype_entry_for_bundle(store, proposal_id)
    classes = _collect_classes_for_bundle(store, proposal_id, already, pending_only=False)
    if not classes and not retype:
        return None
    return _build_bundle(store, proposal_id, retype, classes, ontology_uris)


def diagnose_sub_taxonomy_proposal(
    store: ProposalStore,
    proposal_id: str,
) -> Dict[str, Any]:
    """Explain why a SubTaxonomyProposal id can or cannot be resolved."""
    _ensure_bundle_ids(store)
    subjects = store.subjects_for_sub_taxonomy(proposal_id)
    already = store._ontology_class_uris()
    class_uris = _bundle_class_uris(store, proposal_id)
    retype = _retype_entry_for_bundle(store, proposal_id)

    class_rows: List[Dict[str, Any]] = []
    for cls in store.get_all():
        if cls["uri"] not in class_uris:
            continue
        status = cls.get("status", "pending")
        in_ontology = cls["uri"] in already
        class_rows.append({
            "uri": cls["uri"],
            "label": cls["label"],
            "status": status,
            "in_ontology_ttl": in_ontology,
            "counts_toward_lookup": (
                not in_ontology and status in ("pending", "approved")
            ),
        })

    listable = bool(get_sub_taxonomy_proposal(store, proposal_id))
    pending_list_ids = {b.id for b in list_sub_taxonomy_proposals(store)}

    if listable:
        reason = "ok"
    elif not subjects:
        reason = "no_sub_taxonomy_id_match"
    elif not class_rows and not retype:
        reason = "subjects_without_classes_or_retype"
    elif class_rows and not any(r["counts_toward_lookup"] for r in class_rows) and not retype:
        if all(r["in_ontology_ttl"] for r in class_rows):
            reason = "all_classes_already_in_ontology_ttl"
        elif all(r["status"] == "rejected" for r in class_rows):
            reason = "all_classes_rejected"
        else:
            reason = "no_active_classes"
    elif retype and not class_rows:
        reason = "needs_typing_without_leaf_class"
    else:
        reason = "unknown"

    known_ids: set[str] = set()
    for cls in store.get_all():
        bid = store.get_sub_taxonomy_id(cls["uri"])
        if bid:
            known_ids.add(bid)
    for entry in store.get_needs_typing():
        bid = store.get_sub_taxonomy_id(entry["node"])
        if bid:
            known_ids.add(bid)

    return {
        "proposal_id": proposal_id,
        "found": listable,
        "reason": reason,
        "in_pending_list": proposal_id in pending_list_ids,
        "subject_count": len(subjects),
        "subjects": subjects[:20],
        "classes": class_rows,
        "has_retype_entry": retype is not None,
        "retype_entity_uri": (retype or {}).get("entity_uri"),
        "leaf_class_uri": store.get_leaf_class_uri(retype["node"]) if retype else None,
        "known_bundle_count": len(known_ids),
        "proposal_file": str(store.proposal_file),
        "ontology_file": str(store.ontology_file),
        "proposal_file_exists": store.proposal_file.exists(),
    }


def update_sub_taxonomy_proposal(
    store: ProposalStore,
    proposal_id: str,
    body: Dict[str, Any],
    ontology: Graph,
) -> SubTaxonomyProposal:
    bundle = get_sub_taxonomy_proposal(store, proposal_id)
    if not bundle:
        raise KeyError(f"sub-taxonomy proposal not found: {proposal_id}")

    for link in body.get("subclass_links") or []:
        child = link.get("child_uri")
        parent = link.get("parent_uri")
        source = link.get("source", "manual")
        if child and parent:
            store.add_subclass_of(child, resolve_parent_uri(parent), source=source)

    for cls_update in body.get("proposed_classes") or []:
        uri = cls_update.get("uri")
        if not uri:
            continue
        if cls_update.get("equivalent_class"):
            for equiv in cls_update["equivalent_class"]:
                store.set_equivalent_class(uri, equiv)

    leaf = body.get("leaf_class_uri")
    if leaf:
        retype_node = store.get_retype_node_for_bundle(proposal_id)
        if retype_node:
            store.set_leaf_class_uri(retype_node, resolve_parent_uri(leaf))

    store.save()
    updated = get_sub_taxonomy_proposal(store, proposal_id)
    if not updated:
        raise KeyError(f"sub-taxonomy proposal not found after update: {proposal_id}")
    return updated


def _apply_chain_to_leaf(
    store: ProposalStore,
    leaf_uri: str,
    chain: List[Dict[str, Any]],
    ontology: Graph,
) -> None:
    if not chain:
        return
    if len(chain) == 1 and chain[0].get("uri") and not chain[0].get("qid"):
        store.add_subclass_of(leaf_uri, chain[0]["uri"], source="manual")
        store.save()
        return
    if len(chain) < 2:
        return

    if chain[0].get("qid"):
        clean = normalize_wikidata_qid(chain[0]["qid"])
        store.set_equivalent_class(leaf_uri, wikidata_entity_uri(clean))

    current_uri = leaf_uri
    # approve_with_wikidata_parent calls store.save() internally each iteration.
    # Each new intermediate class gets a random SUB_TAXONOMY_ID from add_class();
    # we overwrite it with the correct bundle ID immediately after.  The try/finally
    # guarantees the corrective store.save() fires even if a later iteration raises,
    # so on-disk state never has orphaned bundle IDs from an intermediate save.
    try:
        for parent_info in chain[1:]:
            if not parent_info.get("qid"):
                # No Wikidata QID → plain ontology reference (uri or label-derived).
                # This covers both explicit ontology URIs and manual label entries.
                target = parent_info.get("uri") or resolve_parent_uri(
                    parent_info.get("label") or ""
                )
                store.add_subclass_of(
                    current_uri, target,
                    source=parent_info.get("source", "manual"),
                )
                break
            result = approve_with_wikidata_parent(
                store, current_uri, parent_info, ontology, mark_approved=False,
            )
            if result.get("new_pending_class"):
                new_uri = result["new_pending_class"]["uri"]
                bid = store.get_sub_taxonomy_id(current_uri)
                if bid:
                    # Fix the random UUID that add_class() wrote before the
                    # intermediate save so the new class belongs to this bundle.
                    store.set_sub_taxonomy_id(new_uri, bid)
                current_uri = new_uri
            else:
                break
    finally:
        store.save()


def _approve_bundle_classes(store: ProposalStore, proposal_id: str) -> int:
    from rdflib import URIRef

    count = 0
    for subject in store.subjects_for_sub_taxonomy(proposal_id):
        if not subject.startswith(ONT_BASE) or "/meta/" in subject:
            continue
        info = store._load_class(URIRef(subject))
        if info.get("status") != "pending":
            continue
        if not info.get("subclass_of"):
            store.set_subclass_of(subject, "http://www.w3.org/2002/07/owl#Thing")
        store.set_status(subject, "approved")
        count += 1
    store.save()
    return count


def _log_sub_taxonomy_approval(
    proposal_id: str,
    action: str,
    bundle: SubTaxonomyProposal,
    merged: int,
    entity_retyped: bool,
) -> None:
    try:
        from src.storage.benchmark_store import create_benchmark_store
        bench = create_benchmark_store()
        if hasattr(bench, "record_sub_taxonomy_approval"):
            bench.record_sub_taxonomy_approval(
                proposal_id=proposal_id,
                action=action,
                leaf_class_uri=bundle.leaf_class_uri,
                entity_uri=bundle.entity_uri,
                class_uris=[c.uri for c in bundle.proposed_classes],
                merged_classes=merged,
                entity_retyped=entity_retyped,
            )
        if hasattr(bench, "close"):
            bench.close()
    except Exception as exc:
        logger.debug("benchmark sub-taxonomy log skipped: %s", exc)


def approve_sub_taxonomy(
    store: ProposalStore,
    proposal_id: str,
    action: str,
    ontology: Graph,
    chain: Optional[List[Dict[str, Any]]] = None,
) -> SubTaxonomyApprovalResult:
    if action not in ("approve", "reject"):
        raise ValueError("action must be approve or reject")

    bundle = get_sub_taxonomy_proposal(store, proposal_id)
    if not bundle:
        diag = diagnose_sub_taxonomy_proposal(store, proposal_id)
        logger.warning(
            "sub-taxonomy proposal not found: %s reason=%s subjects=%s",
            proposal_id,
            diag.get("reason"),
            diag.get("subject_count"),
        )
        raise KeyError(f"sub-taxonomy proposal not found: {proposal_id}")

    if action == "reject":
        store.reject_bundle(proposal_id)
        store.save()
        retype_node = store.get_retype_node_for_bundle(proposal_id)
        if retype_node:
            store.remove_retype_node(retype_node)
            store.save()
        result = SubTaxonomyApprovalResult(action="reject", proposal_id=proposal_id)
        _log_sub_taxonomy_approval(proposal_id, "reject", bundle, 0, False)
        return result

    leaf_uri = bundle.leaf_class_uri
    if not leaf_uri:
        raise ValueError("sub-taxonomy proposal has no leaf class")

    if chain:
        _apply_chain_to_leaf(store, leaf_uri, chain, ontology)
    _approve_bundle_classes(store, proposal_id)

    merged = store.merge_approved_into_ontology()
    entity_retyped = False
    retype_node = store.get_retype_node_for_bundle(proposal_id)
    if retype_node and bundle.entity_uri and bundle.source_ttl:
        entity_retyped = store.resolve_entity_retyping(
            retype_node, leaf_uri, bundle.source_ttl,
        )
        if entity_retyped:
            store.remove_retype_node(retype_node)
            store.save()

    result = SubTaxonomyApprovalResult(
        action="approve",
        proposal_id=proposal_id,
        merged_classes=merged,
        entity_retyped=entity_retyped,
    )
    _log_sub_taxonomy_approval(proposal_id, "approve", bundle, merged, entity_retyped)
    return result


def sub_taxonomy_from_class_uri(
    store: ProposalStore,
    class_uri: str,
) -> Optional[SubTaxonomyProposal]:
    uri = unquote(class_uri)
    bid = store.get_sub_taxonomy_id(uri)
    if bid:
        return get_sub_taxonomy_proposal(store, bid)
    for bundle in list_sub_taxonomy_proposals(store):
        if any(c.uri == uri for c in bundle.proposed_classes):
            return bundle
    return None
