"""
Post-extraction entity resolution pass.

Merges entity variants (case, abbreviations, aliases) into canonical forms
using one or more configurable strategies: rule_based, embedding, llm.
"""
import logging
import math
from typing import Dict, List, Optional, Tuple

from src.config.settings import EntityResolutionSettings

logger = logging.getLogger(__name__)


class EntityResolver:
    """Resolve entity variants into canonical forms."""

    def __init__(self, settings: EntityResolutionSettings, llm_client=None):
        self._settings = settings
        self._llm_client = llm_client  # injected for llm strategy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, entities: List[Dict]) -> List[Dict]:
        """
        Apply configured strategies in order and return deduplicated entity list.

        Each returned entity has a canonical 'entity' name and merged 'type'.
        """
        if not entities or not self._settings.enabled:
            return entities

        # Build mapping: raw_name -> canonical_name
        canonical_map: Dict[str, str] = {e["entity"]: e["entity"] for e in entities if e.get("entity")}

        for strategy in self._settings.strategies:
            if strategy == "rule_based":
                canonical_map = self._apply_rule_based(canonical_map, entities)
            elif strategy == "embedding":
                canonical_map = self._apply_embedding(canonical_map, entities)
            elif strategy == "llm":
                canonical_map = self._apply_llm(canonical_map, entities)
            else:
                logger.warning("Unknown resolution strategy: %s", strategy)

        return self._merge(entities, canonical_map)

    # ------------------------------------------------------------------
    # Strategy: rule_based
    # ------------------------------------------------------------------

    def _apply_rule_based(
        self, canonical_map: Dict[str, str], entities: List[Dict]
    ) -> Dict[str, str]:
        """
        Merge variants based on deterministic rules:
          - ALL_CAPS → Title Case (e.g. HORATIO → Horatio)
          - Known abbreviations from abbreviation_hints
          - Strip common prefixes ("The King" → "King")
        """
        names = list(canonical_map.keys())
        # Build lowercase → name map, preferring non-ALL_CAPS forms when there
        # are multiple names that differ only by case (e.g. Hamlet wins over HAMLET).
        name_set_lower: dict = {}
        for n in names:
            key = n.lower()
            existing = name_set_lower.get(key)
            if existing is None or existing.isupper():
                name_set_lower[key] = n

        hints = {k.lower(): v for k, v in self._settings.abbreviation_hints.items()}

        for name in names:
            canonical = canonical_map[name]

            # Rule 1: ALL_CAPS word(s) → Title Case lookup
            if name == name.upper() and not name.isdigit():
                title = name.title()
                if title.lower() in name_set_lower and title != name:
                    better = name_set_lower[title.lower()]
                    canonical_map[name] = canonical_map.get(better, better)
                    logger.debug("rule_based: %s → %s (title case)", name, canonical_map[name])
                    continue

            # Rule 2: Abbreviation hints
            if name.lower() in hints:
                expansion = hints[name.lower()]
                # Find the expansion in our entity list (case-insensitive)
                if expansion.lower() in name_set_lower:
                    target = name_set_lower[expansion.lower()]
                    canonical_map[name] = canonical_map.get(target, target)
                    logger.debug("rule_based: %s → %s (abbrev hint)", name, canonical_map[name])
                    continue
                # Expansion not in entity list — add it as canonical form anyway
                canonical_map[name] = expansion

            # Rule 3: "The X" → "X"
            if name.startswith("The ") or name.startswith("the "):
                stripped = name[4:]
                if stripped.lower() in name_set_lower:
                    target = name_set_lower[stripped.lower()]
                    canonical_map[name] = canonical_map.get(target, target)
                    logger.debug("rule_based: %s → %s (strip 'The')", name, canonical_map[name])

        return canonical_map

    # ------------------------------------------------------------------
    # Strategy: embedding
    # ------------------------------------------------------------------

    def _apply_embedding(
        self, canonical_map: Dict[str, str], entities: List[Dict]
    ) -> Dict[str, str]:
        """
        Fetch embeddings for all entity names and merge pairs whose
        cosine similarity exceeds the configured threshold.
        """
        names = list(canonical_map.keys())
        if len(names) < 2:
            return canonical_map

        try:
            embeddings = self._get_embeddings(names)
        except Exception as e:
            logger.warning("Embedding strategy failed, skipping: %s", e)
            return canonical_map

        threshold = self._settings.embedding_threshold

        # Find all pairs above threshold
        candidates: List[Tuple[str, str, float]] = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sim = self._cosine(embeddings[i], embeddings[j])
                if sim >= threshold:
                    candidates.append((names[i], names[j], sim))

        if not candidates:
            return canonical_map

        logger.info("Embedding: found %d candidate pair(s) above %.2f", len(candidates), threshold)

        # Optionally confirm with LLM before merging
        if self._settings.llm_confirmation and self._llm_client:
            confirmed = self._llm_confirm_pairs(candidates)
        else:
            confirmed = [(a, b) for a, b, _ in candidates]

        for a, b in confirmed:
            winner = self._pick_canonical(a, b)
            loser = b if winner == a else a
            canonical_map[loser] = canonical_map.get(winner, winner)
            logger.debug("embedding: %s → %s", loser, winner)

        return canonical_map

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Call the OpenAI-compatible /v1/embeddings endpoint."""
        import httpx
        from src.config.settings import load_config

        app = load_config()
        base_url = app.llm.resolved_base_url() or "http://127.0.0.1:1234/v1"
        base_url = base_url.rstrip("/")
        model = self._settings.embedding_model

        headers = {"Content-Type": "application/json"}
        if app.llm.get_api_key():
            headers["Authorization"] = f"Bearer {app.llm.get_api_key()}"

        resp = httpx.post(
            f"{base_url}/embeddings",
            json={"model": model, "input": texts},
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        # Sort by index to preserve order
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # Strategy: llm
    # ------------------------------------------------------------------

    def _apply_llm(
        self, canonical_map: Dict[str, str], entities: List[Dict]
    ) -> Dict[str, str]:
        """
        Ask the LLM to group entity names that refer to the same real-world thing.
        """
        if not self._llm_client:
            logger.warning("LLM strategy requested but no llm_client provided, skipping")
            return canonical_map

        names = list(canonical_map.keys())
        name_list = "\n".join(f"- {n}" for n in names)

        system = (
            "You are an expert at entity coreference resolution. "
            "Given a list of entity names, identify groups that refer to the same real-world entity. "
            "Return ONLY a JSON array of arrays, where each inner array contains names that are the same entity. "
            "Only include groups with 2+ members. Names not in any group are assumed unique."
        )
        user = f"Entity names:\n{name_list}\n\nJSON array of groups (no preamble):"

        try:
            response = self._llm_client.generate(
                prompt=user,
                system_prompt=system,
                max_new_tokens=1024,
                temperature=0.1,
                progress_label="entity resolution · llm",
            ).text
            from src.extraction.json_utils import extract_json
            groups = extract_json(response, prefer="array")
            if not isinstance(groups, list):
                return canonical_map

            name_lower_map = {n.lower(): n for n in names}
            for group in groups:
                if not isinstance(group, list) or len(group) < 2:
                    continue
                # Resolve each name to actual canonical_map key (case-insensitive)
                resolved = [name_lower_map.get(n.lower()) for n in group]
                resolved = [n for n in resolved if n]
                if len(resolved) < 2:
                    continue
                winner = self._pick_canonical(*resolved)
                for loser in resolved:
                    if loser != winner:
                        canonical_map[loser] = canonical_map.get(winner, winner)
                        logger.debug("llm: %s → %s", loser, winner)

        except Exception as e:
            logger.warning("LLM resolution strategy failed: %s", e)

        return canonical_map

    def _llm_confirm_pairs(
        self, candidates: List[Tuple[str, str, float]]
    ) -> List[Tuple[str, str]]:
        """Ask LLM to confirm which candidate pairs should be merged."""
        if not self._llm_client:
            return [(a, b) for a, b, _ in candidates]

        pairs_text = "\n".join(
            f'{i+1}. "{a}" and "{b}" (similarity {s:.2f})'
            for i, (a, b, s) in enumerate(candidates)
        )
        system = (
            "You are an expert at entity coreference. "
            "For each numbered pair, reply 'yes' if they refer to the same entity, 'no' otherwise. "
            "Return ONLY a JSON array of booleans in the same order as the pairs."
        )
        user = f"Pairs:\n{pairs_text}\n\nJSON array of booleans (no preamble):"

        try:
            response = self._llm_client.generate(
                prompt=user,
                system_prompt=system,
                max_new_tokens=256,
                temperature=0.0,
                progress_label="entity resolution · confirm",
            ).text
            from src.extraction.json_utils import extract_json
            decisions = extract_json(response, prefer="array")
            if isinstance(decisions, list):
                return [
                    (a, b)
                    for (a, b, _), ok in zip(candidates, decisions)
                    if ok is True
                ]
        except Exception as e:
            logger.warning("LLM confirmation failed, accepting all candidates: %s", e)

        return [(a, b) for a, b, _ in candidates]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pick_canonical(self, *names: str) -> str:
        """Choose the canonical form from a set of equivalent names."""
        form = self._settings.canonical_form

        if form == "title_case":
            # Prefer names that are already in title case (not all-caps, not all-lower)
            def score(n):
                if n == n.title():
                    return 2
                if not n.isupper():
                    return 1
                return 0
            return max(names, key=lambda n: (score(n), len(n)))

        if form == "longer":
            return max(names, key=len)

        # first_seen — return first in list (caller order)
        return names[0]

    def _merge(self, entities: List[Dict], canonical_map: Dict[str, str]) -> List[Dict]:
        """Apply canonical_map to entity list, merging duplicates.

        Each output entity gains an 'alternate_names' list containing the raw
        variant names that were merged into it (excluding the canonical name itself).
        """
        merged: Dict[str, Dict] = {}
        variants: Dict[str, set] = {}  # canonical → set of raw names

        for entity in entities:
            raw = entity.get("entity", "")
            canonical = canonical_map.get(raw, raw)
            # Walk the chain (in case of multi-hop mappings)
            seen = set()
            while canonical in canonical_map and canonical_map[canonical] != canonical:
                if canonical in seen:
                    break
                seen.add(canonical)
                canonical = canonical_map[canonical]

            if canonical not in merged:
                merged[canonical] = {**entity, "entity": canonical}
                variants[canonical] = set()
            else:
                # Merge type: prefer non-Other
                existing_type = merged[canonical].get("type", "Other")
                new_type = entity.get("type", "Other")
                if existing_type == "Other" and new_type != "Other":
                    merged[canonical]["type"] = new_type

            # Record the raw name as a variant if it differs from canonical
            if raw != canonical:
                variants[canonical].add(raw)

        # Attach alternate_names to each entity (sorted for determinism)
        for canonical, entity in merged.items():
            alts = sorted(variants.get(canonical, set()))
            entity["alternate_names"] = alts

        result = list(merged.values())
        if len(result) < len(entities):
            logger.info(
                "Entity resolution: %d → %d entities (%d merged)",
                len(entities), len(result), len(entities) - len(result),
            )
        return result
