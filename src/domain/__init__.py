"""Domain information model types (not LLM model config or service DTOs)."""
from src.domain.sub_taxonomy import (
    ProposedClass,
    SubTaxonomyApprovalResult,
    SubTaxonomyProposal,
    SubclassLink,
)

__all__ = [
    "ProposedClass",
    "SubclassLink",
    "SubTaxonomyProposal",
    "SubTaxonomyApprovalResult",
]
