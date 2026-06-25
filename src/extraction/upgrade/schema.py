"""Vocabulary, fact model, and free (no-LLM) filters for the upgrade funnel."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

# The complete, closed set of predicates the funnel may emit. Keeping this tiny
# is what makes the constrained LLM prompt cheap and its output trivial to
# validate — anything outside this set is dropped rather than guessed at.
UPGRADE_PREDICATES = (
    "upgradesTo",
    "supportedUpgradeFrom",
    "requiresPrerequisite",
    "deprecatedIn",
    "removedIn",
    "isCompatibleWith",
    "versionOf",
)

# Object-valued predicates whose object is another entity (typed) rather than a
# free-text literal. Used by the writer to decide URI vs Literal.
ENTITY_OBJECT_PREDICATES = frozenset(
    {"upgradesTo", "supportedUpgradeFrom", "isCompatibleWith", "deprecatedIn", "removedIn", "versionOf"}
)

# Signal terms. URL terms gate which pages are fetched at all (stage 1); text
# terms gate which prose chunks reach the LLM (stage 4). Both are pure string
# matching — the cheapest possible filter.
URL_SIGNALS = (
    "upgrad",      # upgrade, upgrading
    "migrat",      # migrate, migration
    "supported-versions",
    "release-notes",
    "compatib",
    "prerequisit",
    "deprecat",
)
TEXT_SIGNALS = (
    "upgrade",
    "upgrading",
    "migrat",
    "supported version",
    "prerequisit",
    "deprecat",
    "removed in",
    "compatib",
    "rolling upgrade",
)


@dataclass(frozen=True)
class UpgradeFact:
    """One upgrade-relevant assertion, with provenance.

    `subject`/`object` are surface strings (product names or version labels);
    canonicalization to URIs happens in the writer. `source` is the page URL or
    local filename the fact came from. `origin` records which funnel stage
    produced it ("table" or "llm") for auditing token spend.
    """

    subject: str
    predicate: str
    object: str
    source: str = ""
    origin: str = ""

    def key(self) -> Tuple[str, str, str]:
        return (self.subject.strip().casefold(), self.predicate, self.object.strip().casefold())

    def is_valid(self) -> bool:
        return (
            bool(self.subject.strip())
            and bool(self.object.strip())
            and self.predicate in UPGRADE_PREDICATES
        )


def is_upgrade_url(url: str) -> bool:
    """True if a URL path looks upgrade-relevant (stage 1 scope filter)."""
    lowered = url.casefold()
    return any(signal in lowered for signal in URL_SIGNALS)


def has_text_signal(text: str) -> bool:
    lowered = text.casefold()
    return any(signal in lowered for signal in TEXT_SIGNALS)


def gate_chunks(chunks: Iterable[str]) -> List[str]:
    """Keep only chunks containing an upgrade signal (stage 4 chunk filter).

    A chunk with no signal never reaches the LLM, so it costs zero tokens.
    """
    return [chunk for chunk in chunks if has_text_signal(chunk)]


def dedupe_facts(facts: Iterable[UpgradeFact]) -> List[UpgradeFact]:
    """Drop invalid facts and collapse exact (subject, predicate, object) repeats.

    Provenance of the first occurrence wins; tables run before the LLM so a
    deterministic fact is preferred over an equivalent LLM-produced one.
    """
    seen: set = set()
    result: List[UpgradeFact] = []
    for fact in facts:
        if not fact.is_valid():
            continue
        fact_key = fact.key()
        if fact_key in seen:
            continue
        seen.add(fact_key)
        result.append(fact)
    return result
