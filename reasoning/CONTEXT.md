# Reasoning

The **Reasoning** bounded context: a downstream system that answers user questions by reasoning over the
KGs/ontology produced by the parent Ingestion context, and renders the reasoning in plain language with an
LLM. It depends only on the parent's published artifacts (see root `CONTEXT-MAP.md`), never on parent
internals.

This file is a glossary only — no implementation details. See `docs/adr/` for this context's decisions.

## Language

### Reasoning

**Reasoning Layer**:
The subsystem that answers user questions by reasoning over the KGs and ontology, then renders the
reasoning in plain language. Distinct from the parent Ingestion context that builds the graph.
_Avoid_: graph-RAG (use only as the general technique), query engine

**Reasoning Vocabulary**:
The small, controlled set of object properties whose instances are trustworthy enough to reason over
(e.g. `supportedOn`, `upgradesTo`, `requires`, `hasVersion`). A curated subset of all extracted predicates.
_Avoid_: schema, predicate list

**Reasoning-Critical Fact**:
An instance-level triple in the Reasoning Vocabulary that an answer depends on
(e.g. `RuntimeVersion_7_1_9 supportedOn OSVersion_RHEL_8_4`). Subject to human verification.
_Avoid_: fact, edge, relationship

**Rule**:
An explicitly authored constraint the reasoning must satisfy, not extracted from documents
(e.g. "every app version in an upgrade path must be supported by an in-scope OS version").
_Avoid_: axiom, policy, requirement

**Reliable Answer**:
An answer where every claim traces to a verified fact or cited snippet, the returned Upgrade Path
satisfies all Rules, and the system **abstains** ("insufficient validated data" + what is missing) rather
than improvising when the verified graph cannot support a conclusion.
_Avoid_: correct answer, confident answer

**Upgrade Path**:
An ordered sequence of Upgrade Steps from a starting version to a target version that satisfies all
applicable Rules. A path MAY mix methods across steps unless a Rule forbids it.
_Avoid_: migration route, chain

**Upgrade Step**:
One validated transition between two SoftwareVersions performed by a specific Upgrade Method. The unit
an Upgrade Path is built from. Reified (n-ary) because it carries the method and its preconditions, not
just `from`/`to`. The same version pair may have several Upgrade Steps (one per validated method).
_Avoid_: edge, hop, upgradesTo (that is the unqualified shorthand)

**Upgrade Method**:
The validated mechanism of an Upgrade Step. Prototype enumeration:
`ZeroDowntimeUpgrade` (in-place rolling; typically step-by-step adjacency),
`SidecarMigration` (new stood up beside old, data migrated, then cut over),
`BigBang` (fresh install of the target version + data migration; MAY skip intermediate versions).
Different methods have different reachability ("jump") semantics.
_Avoid_: strategy, mode, type

**Reasoning Trace**:
The structured, LLM-independent record the reasoning core emits: an ordered list of steps, each with
`{from, to, method, justification}` where justification is a machine reference (verified-fact id, Rule id,
and/or doc snippet). It is the source of truth; the LLM renders it to prose but adds no facts beyond it.
_Avoid_: explanation, log, narrative

**Grounding**:
Resolving a user's free-text answer (e.g. "RHEL 8") to a specific existing graph node
(`OSVersion RHEL 8.4`). Reasoning never runs on ungrounded text; the agent confirms or abstains.
_Avoid_: matching, parsing, lookup

### Version model

**Product**:
A piece of software that has distinct released versions (e.g. Cloudera Runtime, an operating system).
A product node carries no version-specific compatibility itself.
_Avoid_: application, app, package

**SoftwareVersion**:
A first-class node for one released version of a Product (e.g. "Runtime 7.1.9"). The unit that
upgrade paths traverse and that compatibility edges connect.
_Avoid_: release, version string, tag
