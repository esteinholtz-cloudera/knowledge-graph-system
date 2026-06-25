# Reasoning runs over a curated in-memory graph with hand-rolled search

The reasoning layer loads the **verified Reasoning-Vocabulary subset** from a curated TTL
(`reasoning/data/*.ttl`) into a plain in-memory adjacency structure via the existing `rdflib` dependency.
Constrained path search (BFS/Dijkstra/k-shortest) is **hand-rolled** in a small module rather than adding
`networkx`. No external triple store or property-graph DB. The layer reuses shared infra (LLM config,
benchmark store) and the `/api/v1` + GUI patterns; the first surface is a CLI command.

## Why

The trusted/untrusted boundary (Reasoning ADR 0001) is enforced physically by keeping only verified edges
in the reasoning graph. The required traversal is custom anyway — a method-annotated multigraph with
per-edge Rule filters and rule-derived big-bang edges materialized during search (ADR 0002) — so a graph
library's static built-ins add little; the custom successor logic and structured-trace/abstention handling
are the real work. Version graphs are tiny, so performance does not justify a dependency or a database.
This matches the repo guideline favoring a little copying over a little dependency.

## Trade-off accepted

We forgo k-shortest-path helpers (e.g. networkx `shortest_simple_paths`) and reimplement bounded path
enumeration. Accepted for the prototype's small graphs; revisit networkx if enumeration grows complex or the
graph grows large.

## Consequences

- New module `reasoning/src/` owns graph loading, constrained search, trace emission, abstention.
- A curated `reasoning/data/` store holds verified edges + snippet provenance, fed by edge-review (ADR 0001).
