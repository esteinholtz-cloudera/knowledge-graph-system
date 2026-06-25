# PRD: Reasoning prototype — traceable upgrade-path planning over a verified KG

> Reasoning bounded context (`reasoning/`). See `CONTEXT-MAP.md`, `reasoning/CONTEXT.md`, and
> `reasoning/docs/adr/0001-0004` + system-wide `docs/adr/0001`.

## Problem Statement

As a cluster operator, when I need to upgrade my application **and** its underlying OS together, I cannot
get a reliable, traceable answer about whether it is possible and how to do it. The information is spread
across documentation; general LLM assistants confidently hallucinate version compatibility and upgrade
methods; and I have no way to see *why* an answer is correct. For a production cluster, an unverifiable
answer is unusable.

## Solution

A reasoning assistant that asks a few qualifying questions, then reasons over a **human-verified**
knowledge graph plus **authored Rules** to return **ranked, rule-satisfying Upgrade Paths** — each step
annotated with its **Upgrade Method** and justified by a **verified fact** or a **cited documentation
snippet**. When no validated path exists, it **abstains** ("insufficient validated data") and states
exactly what is missing, rather than improvising. The LLM only asks the qualifying questions and renders
the result into plain language; it never performs the reasoning.

## User Stories

1. As an operator, I want to ask "how do I upgrade my app and OS together," so that I can plan a real change.
2. As an operator, I want the assistant to ask me a few targeted qualifying questions, so that it knows my current state before answering.
3. As an operator, I want to state my current application version, so that the path starts from where I am.
4. As an operator, I want to state my current OS version, so that OS support is accounted for.
5. As an operator, I want to state my target version (or say "latest"), so that the path has a goal.
6. As an operator, I want to optionally state my downtime tolerance, so that the methods considered match my constraints.
7. As an operator, when my free-text answer ("RHEL 8") is ambiguous, I want the assistant to show the actual candidate versions and let me pick, so that reasoning runs on a real node (Grounding).
8. As an operator, when my stated version is not in the graph at all, I want the assistant to say so rather than guess, so that I am not misled.
9. As an operator, I want one or more Upgrade Paths from my source to my target, so that I know the route.
10. As an operator, I want each step labeled with its Upgrade Method (ZeroDowntimeUpgrade, SidecarMigration, BigBang), so that I know *how* to perform it.
11. As an operator, I want big-bang options surfaced when they apply (fresh install + data migration, possibly skipping intermediate versions), so that I see shortcuts the docs imply via rule, not just step-by-step routes.
12. As an operator, I want each step checked so that every version in the path is supported by an in-scope OS version, so that the plan is actually valid.
13. As an operator, I want up to k alternative paths ranked by an explainable cost (method preference + number of steps), so that I can choose between e.g. "least downtime" and "fewest steps."
14. As an operator, I want to see the cost/why-ranked for each candidate, so that the ordering is not a black box.
15. As an operator, I want the underlying reasoning path displayed (steps + the relevant subgraph), so that I can inspect the logic directly.
16. As an operator, I want the reasoning converted to clear plain language, so that I do not have to read raw graph data.
17. As an operator, I want every claim in the prose to trace to a verified fact, a Rule, or a cited doc snippet, so that I can trust and audit it.
18. As an operator, I want a clearly separated "Additional context from documentation" section, so that I get helpful supporting snippets without confusing them with proven facts.
19. As an operator, when there is no rule-satisfying path, I want the assistant to abstain and tell me exactly what is missing (e.g. "no validated zero-downtime step from 7.1.7 to 7.1.9"), so that I know what to investigate.
20. As an operator, I want the assistant to never invent a plausible-sounding upgrade that is not backed by verified data, so that I do not act on a hallucination.
21. As a knowledge curator, I want to review candidate reasoning edges (e.g. `supportedOn`, `upgradesTo`) and accept/edit/reject them, so that only trustworthy facts are reasoned over.
22. As a knowledge curator, I want accepted edges to capture the supporting sentence + document + location, so that answers can cite exact snippets.
23. As a knowledge curator, I want to seed the verified edge set by hand for the first domain, so that a working demo does not wait on a full review UI.
24. As a maintainer, I want the reasoning system to read only the parent's published artifacts (TTL/ontology/metadata), so that the two contexts stay separable.
25. As a maintainer, I want a CLI command to run a reasoning query end-to-end, so that I can validate the core before building API/GUI.
26. As a maintainer, I want reasoning runs and reliability metrics logged to the existing benchmark store, so that I can measure quality over time.
27. As an evaluator, I want a gold set including deliberately unanswerable questions, so that abstention behavior is measured, not assumed.
28. As an evaluator, I want path correctness, rule compliance, abstention precision/recall, and citation validity reported, so that "reliable" is quantified.

## Implementation Decisions

- **Context boundary.** All work lives in the Reasoning context (`reasoning/`), depending only on the
  parent's published artifacts via the `CONTEXT-MAP.md` contract; shared infra (LLM client/config,
  benchmark store) is consumed from a small shared location, not parent internals. (System-wide ADR 0001.)
- **Substrate.** Reason only over a curated **Reasoning Vocabulary** of object properties whose
  instance-level facts are **human-verified**; **Rules** are authored explicitly, not extracted.
  (Reasoning ADR 0001.)
- **Version model.** Versions are first-class `SoftwareVersion` nodes linked to `Product` via `hasVersion`;
  compatibility via `supportedOn`; transitions via reified per-method **Upgrade Steps**. (CONTEXT, ADR 0002.)
- **Reachability.** Zero-downtime/sidecar steps are explicit verified facts; big-bang reachability is a
  Rule. The upgrade graph is a multigraph. (Reasoning ADR 0002.)
- **Reasoning core.** A deterministic graph search (BFS/Dijkstra/A*, hand-rolled, no networkx) over an
  in-memory graph built from the verified TTL; Rules expressed in SHACL/SPARQL as edge filters + path
  validators; OWL/DL only for entity typing; the LLM is excluded from the core. (Reasoning ADR 0003, 0004.)
- **Results.** Return up to k candidate paths ranked by an explainable additive cost dominated by method
  preference (zero-downtime < sidecar < big-bang) then step count.
- **Fact-gathering.** A fixed required-slot schema (source product+version, source OS+version, target or
  "latest", optional downtime tolerance); the LLM runs the dialogue and **grounds** answers to real nodes;
  confirm-or-abstain when ungroundable.
- **Transparency.** The core emits a structured **Reasoning Trace** (ordered steps with machine
  justification references). The LLM **renders** prose strictly from the trace; the UI also exposes the raw
  path and subgraph. Verified edges carry snippet-level provenance.
- **Answer synthesis.** Render → automated **grounding check** (every version/method/product/claim must
  appear in the trace) → deterministic **template fallback** on failure. A separate "Additional context"
  zone shows snippets already linked to path nodes/edges; never blended with verified reasoning.
- **Reliability stance.** Strict **abstention** when the verified graph + Rules cannot support a conclusion.
- **Surfaces.** CLI command first; `/api/v1`-style endpoint and a GUI page reuse parent patterns later; the
  GUI talks to both contexts over HTTP.
- **Module interfaces (shape, not files).**
  - `ReasoningQuery`: the filled slot set (source product/version, source OS/version, target, downtime
    tolerance).
  - `AnswerResult`: `candidate_paths` (each: ordered steps with method + per-step justification + cost),
    `abstained` flag with `missing[]`, `reasoning_trace`, `additional_context` (cited snippets), and the
    rendered prose.
- **No vector store** for the prototype; supplementary context comes from snippets already attached to the
  path's nodes/edges.

## Testing Decisions

- **What a good test is here:** asserts only **external behavior** at the boundary — the structure and
  content of `AnswerResult` for a given query against a known graph — never internal traversal state.
- **Primary seam:** `ReasoningService.answer(query) -> AnswerResult`, driven with a **curated in-memory
  reasoning-graph fixture** (small TTL in a temp dir) and an **injected/mock LLM**. Cases assert: correct
  ranked paths; correct methods per step; rule compliance; correct **abstention** + `missing[]` for
  unanswerable inputs; citations resolve to verified facts/snippets.
- **Secondary seam:** pure `verify_rendering(trace, prose) -> violations` — feed prose containing a
  version/method **absent** from the trace and assert it is flagged (the hallucination guard); no mocks.
- **Modules tested:** the Reasoning service boundary and the rendering verifier. The deterministic search +
  Rule validation are exercised through the service seam via crafted fixtures (including paths that must be
  rejected for rule violations).
- **Gold set:** a hand-curated set for the first (Cloudera upgrade) domain, **including deliberate
  unanswerable cases**; metrics — path correctness, **rule compliance (target 1.0)**, abstention
  precision/recall, citation validity — logged to the existing DuckDB benchmark store.
- **Prior art:** the parent's `test_services_pipeline.py` (service constructed with injected factories,
  mocked LLM, asserts on the result dataclass + progress events) is the pattern to mirror in
  `reasoning/tests/`.

## Out of Scope

- General open-domain Q&A over the KG (this prototype is upgrade/migration path planning only).
- **Joint app+OS path planning across two coupled version graphs** — the headline example ultimately needs
  this; the prototype models a single upgrade graph and treats OS support as a per-step constraint. Flagged
  as the most likely next phase.
- A vector index / hybrid retrieval RAG.
- A full instance-triple review UI (only a lightweight edge-review / hand-seeding is in scope).
- Automatic extraction of Rules from documents (Rules are authored).
- Production hardening, auth, multi-tenant concerns.
- The unified GUI build (only the HTTP-API boundary that enables it later).

## Further Notes

- **Biggest real-world risk is not the reasoning — it is populating the verified graph.** Answers are only
  as good as the curated Upgrade Steps and `supportedOn` facts. The first build effort is the Reasoning
  Vocabulary + version-node sourcing + edge-review, not the search algorithm.
- **Split-readiness:** the `reasoning/` boundary is a deliberate on-ramp to a separate repo if needed; the
  one-way artifact dependency, small `shared/`, and HTTP-only GUI coupling keep that split cheap (system-wide
  ADR 0001).
- Strict abstention, structured-trace rendering, and gold-set evaluation were adopted as defaults during
  design; revisit if product direction changes.
