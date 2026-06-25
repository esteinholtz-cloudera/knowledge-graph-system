# Reasoning core is deterministic graph search; the LLM is excluded from it

Upgrade Path planning is performed by a **deterministic graph-search algorithm** (BFS for fewest-steps,
Dijkstra/A* when steps carry costs) over the Upgrade-Step multigraph. **Rules** are expressed
declaratively (SHACL/SPARQL) and applied as edge filters and whole-path validators. OWL/DL reasoning is
retained only for its existing job — **entity typing/classification** in the parent. The **LLM never
participates in the reasoning core**; it only gathers facts up front and explains results afterward.

## Why

The query class is pathfinding, and graph search is the tool built for it: it returns the ordered,
annotated route (transparency), supports cost optimization (best path, not just a path), and yields a
natural "no path found" for abstention under a closed-world reading. DL/SWRL reasoners answer reachability
but discard the route, lack cost/optimization, struggle with path-dependent constraints, and resist
negation (open-world) — so they cannot produce "do these steps, in this order, here is why, and it is the
lowest-cost option." GNN/embedding rankers are not traceable; LLM-in-the-loop reintroduces hallucination.

## Trade-off accepted

We forgo the inference convenience of a rule engine for paths and instead maintain explicit search +
declarative rule artifacts. Accepted because traceability and abstention are the project's reason to exist.

## Consequences

- Need a graph representation suited to traversal (in-memory graph built from the verified KG subset).
- Rules live as SHACL shapes / SPARQL the search invokes; keep them small and inspectable.
- A cost model and result-ranking policy must be defined (separate decision).
