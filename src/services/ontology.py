"""Ontology proposal status, approval, review, and visualization."""
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from rdflib import Graph

from src.config.settings import load_config
from src.ontology.review_helpers import (
    apply_proposal_decision,
    approve_with_wikidata_parent,
    parent_choices_from_wikidata,
    pick_wikidata_entity,
    search_wikidata,
    suggest_parents,
)
from src.ontology.sub_taxonomy_service import (
    approve_sub_taxonomy,
    diagnose_sub_taxonomy_proposal,
    get_sub_taxonomy_proposal,
    list_sub_taxonomy_proposals,
    sub_taxonomy_from_class_uri,
    update_sub_taxonomy_proposal,
)
from src.services.artifacts import ArtifactService
from src.services.models import ApproveOntologyResult, OntologyStatusResult


class OntologyService:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        artifact_service: Optional[ArtifactService] = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._artifacts = artifact_service or ArtifactService(self.project_root)

    def _paths(self, ontology_dir: str = "data/ontology"):
        base = self.project_root / ontology_dir
        return base / "ontology_proposed.ttl", base / "ontology.ttl"

    def _store(self, ontology_dir: str = "data/ontology"):
        from src.ontology.proposal_store import ProposalStore

        proposal_file, ontology_file = self._paths(ontology_dir)
        return ProposalStore(str(proposal_file), str(ontology_file))

    def _load_ontology_graph(self, ontology_dir: str = "data/ontology") -> Graph:
        _, ontology_file = self._paths(ontology_dir)
        g = Graph()
        if ontology_file.exists():
            g.parse(str(ontology_file), format="turtle")
        return g

    def _bundle_dicts(self, ontology_dir: str = "data/ontology") -> List[Dict[str, Any]]:
        proposal_file, _ = self._paths(ontology_dir)
        if not proposal_file.exists():
            return []
        store = self._store(ontology_dir)
        return [b.to_dict() for b in list_sub_taxonomy_proposals(store)]

    def status(self, ontology_dir: str = "data/ontology") -> OntologyStatusResult:
        proposal_file, _ = self._paths(ontology_dir)
        if not proposal_file.exists():
            return OntologyStatusResult(
                summary={},
                sub_taxonomy_proposals=[],
                pending=[],
                needs_typing=[],
            )
        store = self._store(ontology_dir)
        bundles = [b.to_dict() for b in list_sub_taxonomy_proposals(store)]
        return OntologyStatusResult(
            summary=store.status_summary(),
            sub_taxonomy_proposals=bundles,
            pending=[b for b in bundles if not b.get("is_needs_typing")],
            needs_typing=[b for b in bundles if b.get("is_needs_typing")],
        )

    def list_sub_taxonomy(
        self,
        ontology_dir: str = "data/ontology",
    ) -> List[Dict[str, Any]]:
        return self._bundle_dicts(ontology_dir)

    def get_sub_taxonomy(
        self,
        proposal_id: str,
        ontology_dir: str = "data/ontology",
    ) -> Optional[Dict[str, Any]]:
        store = self._store(ontology_dir)
        bundle = get_sub_taxonomy_proposal(store, proposal_id)
        return bundle.to_dict() if bundle else None

    def diagnose_sub_taxonomy(
        self,
        proposal_id: str,
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        store = self._store(ontology_dir)
        diag = diagnose_sub_taxonomy_proposal(store, proposal_id)
        diag["project_root"] = str(self.project_root)
        return diag

    def update_sub_taxonomy(
        self,
        proposal_id: str,
        body: Dict[str, Any],
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        store = self._store(ontology_dir)
        ontology = self._load_ontology_graph(ontology_dir)
        return update_sub_taxonomy_proposal(
            store, proposal_id, body, ontology,
        ).to_dict()

    def sub_taxonomy_approval(
        self,
        proposal_id: str,
        action: str,
        chain: Optional[List[Dict]] = None,
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        store = self._store(ontology_dir)
        ontology = self._load_ontology_graph(ontology_dir)
        result = approve_sub_taxonomy(
            store, proposal_id, action, ontology, chain=chain,
        )
        return result.to_dict()

    def list_proposals(
        self,
        filter_name: Optional[str] = None,
        ontology_dir: str = "data/ontology",
    ) -> List[Dict[str, Any]]:
        bundles = self._bundle_dicts(ontology_dir)
        if filter_name == "pending":
            return [b for b in bundles if not b.get("is_needs_typing")]
        if filter_name == "needs_typing":
            return [b for b in bundles if b.get("is_needs_typing")]
        if filter_name in ("approved", "rejected"):
            store = self._store(ontology_dir)
            return [c for c in store.get_all() if c.get("status") == filter_name]
        return bundles

    def _resolve_review_uri(
        self,
        class_uri: str,
        ontology_dir: str = "data/ontology",
    ) -> str:
        """Map sub-taxonomy id or class uri to a class uri for Wikidata/LLM helpers."""
        store = self._store(ontology_dir)
        uri = unquote(class_uri)
        bundle = get_sub_taxonomy_proposal(store, uri)
        if bundle and bundle.leaf_class_uri:
            return bundle.leaf_class_uri
        found = sub_taxonomy_from_class_uri(store, uri)
        if found and found.leaf_class_uri:
            return found.leaf_class_uri
        return uri

    def get_proposal(self, class_uri: str, ontology_dir: str = "data/ontology") -> Optional[Dict[str, Any]]:
        uri = unquote(class_uri)
        store = self._store(ontology_dir)
        bundle = get_sub_taxonomy_proposal(store, uri)
        if bundle:
            return bundle.to_dict()
        found = sub_taxonomy_from_class_uri(store, uri)
        if found:
            return found.to_dict()
        for cls in self._store(ontology_dir).get_all():
            if cls.get("uri") == uri:
                return cls
        return None

    def update_proposal(
        self,
        class_uri: str,
        body: Dict[str, Any],
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        store = self._store(ontology_dir)
        uri = unquote(class_uri)
        bundle = get_sub_taxonomy_proposal(store, uri) or sub_taxonomy_from_class_uri(store, uri)
        if bundle and (body.get("subclass_links") or body.get("proposed_classes") or body.get("leaf_class_uri")):
            return self.update_sub_taxonomy(bundle.id, body, ontology_dir)
        review_uri = bundle.leaf_class_uri if bundle else self._resolve_review_uri(uri, ontology_dir)
        status = body.get("status")
        parent = body.get("parent_class_uri")
        wikidata_id = body.get("wikidata_id")
        if status and status not in ("approved", "rejected", "pending"):
            raise ValueError("status must be approved, rejected, or pending")
        return apply_proposal_decision(
            store,
            review_uri,
            status=status,
            parent_class_uri=parent,
            wikidata_id=wikidata_id,
            ontology=self._load_ontology_graph(ontology_dir),
        )

    def _wikidata_mode(self) -> str:
        return load_config().ontology.wikidata_mcp

    def search_wikidata(
        self,
        class_uri: str,
        search_term: Optional[str] = None,
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        proposal = self.get_proposal(class_uri, ontology_dir)
        if not proposal:
            raise KeyError(f"proposal not found: {class_uri}")
        term = search_term or proposal.get("label", "")
        hits, wd_err = search_wikidata(term, self._wikidata_mode())
        return {
            "search_term": term,
            "wikidata_hits": hits[:10],
            "wikidata_error": wd_err,
        }

    def select_wikidata_entity(
        self,
        class_uri: str,
        qid: str,
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        store = self._store(ontology_dir)
        uri = self._resolve_review_uri(class_uri, ontology_dir)
        parents = pick_wikidata_entity(store, uri, qid, self._wikidata_mode())
        ontology = self._load_ontology_graph(ontology_dir)
        return {
            "selected_qid": qid,
            "wikidata_parents": parents,
            "parent_choices": parent_choices_from_wikidata(parents, ontology),
            "proposal": self.get_proposal(class_uri, ontology_dir),
        }

    def approve_wikidata_parent(
        self,
        class_uri: str,
        parent_qid: str,
        parent_label: Optional[str] = None,
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        from src.ontology.review_helpers import normalize_wikidata_qid

        store = self._store(ontology_dir)
        uri = self._resolve_review_uri(class_uri, ontology_dir)
        ontology = self._load_ontology_graph(ontology_dir)
        qid = normalize_wikidata_qid(parent_qid)
        parent_info = {"qid": qid, "label": parent_label or qid}
        result = approve_with_wikidata_parent(store, uri, parent_info, ontology)
        bundle = sub_taxonomy_from_class_uri(store, uri)
        if bundle and result.get("new_pending_class"):
            new_uri = result["new_pending_class"]["uri"]
            store.set_sub_taxonomy_id(new_uri, bundle.id)
            store.save()
        return result

    def suggest_placement(
        self,
        class_uri: str,
        ontology_dir: str = "data/ontology",
        search_term: Optional[str] = None,
        ancestor_chain: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        proposal = self.get_proposal(class_uri, ontology_dir)
        if not proposal:
            raise KeyError(f"proposal not found: {class_uri}")
        label = search_term or proposal.get("label", "")
        context = ""
        if proposal.get("proposed_classes"):
            context = proposal["proposed_classes"][0].get("comment", "")
        elif proposal.get("comment"):
            context = proposal["comment"]
        llm_client = None
        try:
            from src.extraction.llm_client import LLMClient
            llm_client = LLMClient.from_config()
        except Exception:
            pass
        return suggest_parents(
            label,
            self._load_ontology_graph(ontology_dir),
            llm_client=llm_client,
            context=context,
            ancestor_chain=ancestor_chain,
        )

    def get_wikidata_p279_chain(
        self,
        qid: str,
        max_depth: int = 12,
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        from src.ontology.review_helpers import normalize_wikidata_qid, parent_choices_from_wikidata, wikidata_p279_chain

        clean = normalize_wikidata_qid(qid)
        chain = wikidata_p279_chain(clean, self._wikidata_mode(), max_depth=max_depth)
        ontology = self._load_ontology_graph(ontology_dir)
        parent_choices = parent_choices_from_wikidata(
            chain[1:] if len(chain) > 1 else [],
            ontology,
        )
        return {"qid": clean, "chain": chain, "parent_choices": parent_choices}

    def get_wikidata_superclasses(self, qid: str, ontology_dir: str = "data/ontology") -> Dict[str, Any]:
        from src.ontology.review_helpers import normalize_wikidata_qid, parent_choices_from_wikidata, wikidata_superclasses

        clean = normalize_wikidata_qid(qid)
        parents = wikidata_superclasses(clean, self._wikidata_mode())
        ontology = self._load_ontology_graph(ontology_dir)
        return {
            "qid": clean,
            "parents": parents,
            "parent_choices": parent_choices_from_wikidata(parents, ontology),
        }

    def approve_chain(
        self,
        proposal_uri: str,
        chain: List[Dict],
        ontology_dir: str = "data/ontology",
    ) -> Dict[str, Any]:
        """Deprecated: use sub_taxonomy_approval. Resolves class uri to bundle id."""
        store = self._store(ontology_dir)
        uri = unquote(proposal_uri)
        bundle = get_sub_taxonomy_proposal(store, uri) or sub_taxonomy_from_class_uri(store, uri)
        if not bundle:
            raise KeyError(f"proposal not found: {proposal_uri}")
        if len(chain) < 2:
            raise ValueError("chain must have at least 2 nodes (entity + one parent)")
        return self.sub_taxonomy_approval(
            bundle.id, "approve", chain=chain, ontology_dir=ontology_dir,
        )

    def approve(self, ontology_dir: str = "data/ontology") -> ApproveOntologyResult:
        from src.storage.ontology_manager import OntologyManager

        path = self.project_root / ontology_dir
        manager = OntologyManager(str(path))
        n = manager.approve_proposed_ontology()
        return ApproveOntologyResult(approved_count=n)

    def approve_all(self, ontology_dir: str = "data/ontology") -> ApproveOntologyResult:
        return self.approve(ontology_dir)

    def visualize(self, ontology_dir: str = "data/ontology") -> Optional[str]:
        _, ontology_file = self._paths(ontology_dir)
        if not ontology_file.exists():
            return None
        output_path = self.project_root / "data" / "documents" / "ontology_graph.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._artifacts.generate_graph_from_ttl(
            str(ontology_file), str(output_path),
        )
        return result.output_path

    def run_interactive_review(self, ontology_dir: str = "data/ontology") -> None:
        from src.ontology.interactive_review import run_interactive_review

        app_config = load_config()
        proposal_file, ontology_file = self._paths(ontology_dir)
        try:
            from src.extraction.llm_client import LLMClient
            llm_client = LLMClient.from_config()
        except Exception:
            llm_client = None

        run_interactive_review(
            proposal_file=str(proposal_file),
            ontology_file=str(ontology_file),
            llm_client=llm_client,
            wikidata_mode=app_config.ontology.wikidata_mcp,
        )
