# Ingestion and Reasoning are separate bounded contexts in one repo

The repository holds two bounded contexts: **Ingestion** (root `src/` — documents → KG/ontology) and
**Reasoning** (`reasoning/` subtree — inference/answering over the KG/ontology). The Reasoning context has
its own `src/`, `data/`, `docs/` (incl. `docs/adr/`), and `CONTEXT.md`. The dependency is **one-way and
artifact-level**: Reasoning consumes only the parent's published artifacts (TTL KGs, `ontology.ttl`,
`metadata.json`) per the contract in `CONTEXT-MAP.md`, never the parent's internal modules. Genuinely
shared, stable infra (LLM client/config, benchmark store) is extracted to a small shared location; a single
GUI may talk to both contexts' HTTP APIs.

## Why

The two phases have different responsibilities and lifecycles. Keeping them as one undifferentiated module
would entangle ingestion churn with reasoning correctness and blur the trusted/untrusted data boundary that
the reasoning design depends on (Reasoning ADR 0001). A directory boundary with a data contract keeps the
mother project focused and the reasoning project independently evolvable, while still allowing a unified GUI.

## Trade-off accepted

Some duplication and an explicit artifact contract instead of convenient cross-imports. Accepted because the
contract is exactly the surface we would expose anyway, and it keeps each context simple.

## Consequences — designed to be split-ready

This boundary is a deliberate on-ramp to separate git repositories **if** that proves necessary. A clean
split stays cheap **only while** these invariants hold:

- **One-way dependency**: Reasoning never imports parent internals — only reads published artifacts. A split
  then becomes "move the directory + repoint the artifact source (path → URL/registry)".
- **Data, not code, is the contract**: the TTL/ontology surface is versionable and already cross-repo-shaped.
- **`shared/` stays small and dependency-light** so it can become a tiny published package or be vendored.
- **The GUI talks to both contexts over HTTP (`/api/v1`)**, not via a shared build.

Forfeiting the option would look like: cross-imports into parent `src/`, one test suite spanning both
contexts, shared mutable state, or a single config entangling both contexts' settings. The split itself (the
hard-to-reverse act) is deferred until proven necessary.
