# Upgrade steps are reified per method; big-bang reachability is rule-derived

An Upgrade Step is a reified (n-ary) node carrying `from`, `to`, and `Upgrade Method`
(`ZeroDowntimeUpgrade`, `SidecarMigration`, `BigBang`). The upgrade graph is therefore a multigraph:
several validated steps may connect the same version pair. Reachability is determined **per method**:
zero-downtime and sidecar steps are **explicit human-verified facts** from documentation; big-bang
reachability is a **Rule** ("fresh install of any supported newer target + data migration").

## Why

Cluster software upgrades have multiple validated mechanisms with different "jump" semantics. Zero-downtime
and sidecar are validated for specific version pairs in docs, so storing them as explicit facts preserves
the verified-fact guarantee. Big-bang is fundamentally a fresh install plus data migration; its validity is
governed by data-migration support, which is rule-shaped, not pairwise-documented — enumerating every
big-bang target as an explicit edge would explode combinatorially without adding traceability.

## Trade-off accepted

A big-bang step in a returned path is justified by a Rule rather than a single cited sentence, so its
provenance is "rule + the data-migration support fact it depends on" instead of one document quote.
Accepted because the alternative (enumerate all big-bang edges) is high-curation and still rule-like in
practice.

## Consequences

- Pathfinding traverses a multigraph of Upgrade Steps; the engine must materialize rule-derived big-bang
  steps (or evaluate the rule during traversal).
- Reuses the parent's planned `ont:QualifiedRelation` n-ary pattern.
