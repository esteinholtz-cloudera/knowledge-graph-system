"""Token-conservative extraction of product upgrade facts into TTL.

A funnel that strips content for *zero* tokens before any LLM is involved:

    scope (URL/sitemap filter)  →  dedupe (content hash)
        →  tables (deterministic HTML parse)  →  keyword-gated prose chunks
            →  one constrained LLM pass  →  TTL

Only the final stage spends tokens, and only on short, upgrade-relevant prose
that was not already captured deterministically from tables.
"""
from .schema import (
    UPGRADE_PREDICATES,
    UpgradeFact,
    dedupe_facts,
    gate_chunks,
    is_upgrade_url,
)
from .runner import UpgradeProgress, UpgradeRunResult, run_upgrade_extraction
from .writer import write_upgrade_ttl

__all__ = [
    "UPGRADE_PREDICATES",
    "UpgradeFact",
    "UpgradeProgress",
    "UpgradeRunResult",
    "dedupe_facts",
    "gate_chunks",
    "is_upgrade_url",
    "run_upgrade_extraction",
    "write_upgrade_ttl",
]
