# Reasoning layer separates trusted reasoning data from raw extraction

The reasoning layer does **not** reason over the raw extracted KG. Instead it reasons over a small
**Reasoning Vocabulary** (curated object properties such as `supportedOn`, `upgradesTo`, `requires`,
`hasVersion`), whose **instance-level facts are human-verified** before use, plus **Rules** that are
**authored explicitly** (code/SHACL/SPARQL) rather than extracted. Versions are modeled as
**first-class `SoftwareVersion` nodes** so upgrade paths can be traversed as graph paths.

## Why

The parent (Ingestion) pipeline produces ad-hoc `kg:` predicates (inconsistent, unverified) and a
class-only ontology with no object-property axioms or rules (see parent `TODO.md` "Axioms and rules").
Reasoning that must be *reliable* and *fully traceable* (the project goal) cannot stand on facts the LLM
guessed once, nor on rules inferred from prose. Splitting **extracted-but-untrusted** from
**verified-and-reasoned-over** makes correctness auditable; authoring rules separately keeps them
inspectable and stable.

## Trade-off accepted

More upfront work (define the vocabulary, build a lightweight edge-review, author rules) and the
reasoning layer ignores most of what extraction produces. Rejected alternative: let an LLM interpret the
raw KG at query time — simpler, but neither reliable nor auditable.

## Consequences

- A new lightweight **reasoning-edge review** is needed (the parent's review covers ontology *classes* and
  predicate normalization, not instance triples). Prototype may seed verified edges by hand-curation.
- The Reasoning context populates its Reasoning Vocabulary and version-node model from the parent's
  published artifacts; if extraction must be extended to emit them, that is parent (Ingestion) work
  consumed across the artifact contract (see root [CONTEXT-MAP.md](../../../CONTEXT-MAP.md)).
