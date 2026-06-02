import { Fragment, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  approveOntology,
  approveSubTaxonomy,
  getOntologyStatus,
  getWikidataSuperclasses,
  searchWikidata,
  suggestPlacement,
  updateOntologyProposal,
} from "../api/client";
import type {
  OntologyProposal,
  PlacementSuggestion,
  SubTaxonomyProposal,
  SuggestPlacementResponse,
  WikidataHit,
  WikidataParentChoice,
} from "../api/types";

// ── local types ───────────────────────────────────────────────────────────────

interface ChainNode {
  qid?: string;
  label: string;
  uri?: string;           // ontology URI when sourced from LLM
  source: "wikidata" | "llm";
}

interface LevelState {
  label: string;
  qid?: string;           // Wikidata QID linked at this level
  llmProposals: PlacementSuggestion[];
  wikidataHits: WikidataHit[];
  parentChoices: WikidataParentChoice[];
  wdSearchTerm: string;
}

// ── helpers ───────────────────────────────────────────────────────────────────

function extractLabel(uri: string): string {
  return decodeURIComponent(uri.split(/[/#]/).pop() ?? uri).replace(/_/g, " ");
}

function mergeChoices(a: WikidataParentChoice[], b: WikidataParentChoice[]): WikidataParentChoice[] {
  const seen = new Set(a.map((x) => x.qid));
  return [...a, ...b.filter((x) => !seen.has(x.qid))];
}

function wikidataTitle(hit: { qid: string; label?: string }) {
  const label = hit.label?.trim();
  return label && label !== hit.qid ? (
    <>
      <strong>{label}</strong>
      <span className="muted"> ({hit.qid})</span>
    </>
  ) : (
    <strong>{hit.qid}</strong>
  );
}

function emptyLevel(label: string): LevelState {
  return { label, qid: undefined, llmProposals: [], wikidataHits: [], parentChoices: [], wdSearchTerm: label };
}

// ── sub-components ────────────────────────────────────────────────────────────

function ChainViz({
  proposal,
  entityQid,
  chain,
  onRollback,
  onReset,
}: {
  proposal: SubTaxonomyProposal;
  entityQid: string | null;
  chain: ChainNode[];
  onRollback: (i: number) => void;
  onReset: () => void;
}) {
  return (
    <div className="chain-viz">
      <div className="chain-viz__header">
        <span className="chain-viz__title">Taxonomy chain</span>
        <button type="button" className="chain-viz__reset" onClick={onReset}>
          ✕ reset
        </button>
      </div>
      <div className="chain-viz__body">
        <div className="chain-node chain-node--proposal">
          {proposal.label}
          <span className="chain-tag">proposal</span>
        </div>
        {entityQid && (
          <>
            <div className="chain-arrow">≡ Wikidata</div>
            <div className="chain-node chain-node--entity">
              <span className="muted">{entityQid}</span>
            </div>
          </>
        )}
        {chain.map((node, i) => (
          <Fragment key={`${node.qid ?? node.label}-${i}`}>
            <div className="chain-arrow">↑ subclassOf</div>
            <button
              type="button"
              className={`chain-node chain-node--clickable ${
                i === chain.length - 1 ? "chain-node--current" : "chain-node--ancestor"
              }`}
              title="Click to roll back to this level"
              onClick={() => onRollback(i)}
            >
              {node.qid ? wikidataTitle(node as WikidataHit) : <strong>{node.label}</strong>}
              <span className="chain-tag">{node.source}</span>
            </button>
          </Fragment>
        ))}
        <div className="chain-arrow chain-arrow--pending">↑ select next parent…</div>
      </div>
    </div>
  );
}

function ProposalGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginTop: "0.75rem" }}>
      <div className="proposals-group-header">{title}</div>
      {children}
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

function proposalReviewUri(p: SubTaxonomyProposal): string {
  return p.leaf_class_uri || p.proposed_classes[0]?.uri || p.id;
}

export function Ontology() {
  const [pending, setPending] = useState<SubTaxonomyProposal[]>([]);
  const [needsTyping, setNeedsTyping] = useState<SubTaxonomyProposal[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<SubTaxonomyProposal | null>(null);

  // chain[0] = first selected parent; chain[1] = second selected parent; etc.
  // entityQid = Wikidata entity linked as equivalentClass (separate from chain)
  const [chain, setChain] = useState<ChainNode[]>([]);
  const [history, setHistory] = useState<LevelState[]>([]);
  const [current, setCurrent] = useState<LevelState>(emptyLevel(""));
  const [entityQid, setEntityQid] = useState<string | null>(null);

  const [parentUri, setParentUri] = useState("http://www.w3.org/2002/07/owl#Thing");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await getOntologyStatus();
      setSummary(data.summary);
      setPending(data.pending);
      setNeedsTyping(data.needs_typing);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load proposals");
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  function resetChain() {
    setChain([]);
    setHistory([]);
    setEntityQid(null);
  }

  // TODO: fix ancestral chain LLM/Wikidata — at each level, LLM suggestions should
  // use the ancestor's own ontology context (not the original proposal URI), and
  // Wikidata P279 traversal should follow the selected entity's full superclass chain
  // rather than only the immediate parents fetched per level.
  async function buildLevelState(
    label: string,
    qid: string | undefined,
    proposalUri: string,
  ): Promise<LevelState> {
    const [suggest, superData] = await Promise.all([
      suggestPlacement(proposalUri, label).catch((): SuggestPlacementResponse => ({
        proposals: [], wikidata_hits: [], wikidata_parents: [], parent_choices: [],
      })),
      qid
        ? getWikidataSuperclasses(qid).catch(() => ({ qid: "", parents: [], parent_choices: [] }))
        : Promise.resolve({ qid: "", parents: [], parent_choices: [] }),
    ]);

    const autoQid = suggest.selected_wikidata_qid ?? undefined;
    const merged = mergeChoices(suggest.parent_choices ?? [], superData.parent_choices ?? []);
    return {
      label,
      qid: qid ?? autoQid,
      llmProposals: suggest.proposals ?? [],
      wikidataHits: suggest.wikidata_hits ?? [],
      parentChoices: merged,
      wdSearchTerm: label,
    };
  }

  async function loadProposal(proposal: SubTaxonomyProposal) {
    setSelected(proposal);
    resetChain();
    setLoading(true);
    setMsg("");
    setError("");
    try {
      const reviewUri = proposalReviewUri(proposal);
      const state = await buildLevelState(proposal.label, undefined, reviewUri);
      setCurrent(state);
      const leaf = proposal.proposed_classes.find((c) => c.uri === proposal.leaf_class_uri);
      if (leaf?.subclass_of?.[0]) setParentUri(leaf.subclass_of[0]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load suggestions");
    } finally {
      setLoading(false);
    }
  }

  async function selectParent(node: ChainNode) {
    if (!selected) return;
    setLoading(true);
    try {
      setHistory((h) => [...h, current]);
      setChain((c) => [...c, node]);
      const nextState = await buildLevelState(node.label, node.qid, proposalReviewUri(selected));
      setCurrent(nextState);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load next level");
    } finally {
      setLoading(false);
    }
  }

  function rollbackTo(i: number) {
    // Restores the state that was active just before chain[i] was selected.
    setCurrent(history[i]);
    setChain((c) => c.slice(0, i));
    setHistory((h) => h.slice(0, i));
    setError("");
    setMsg("");
  }

  async function linkWikidataEntity(hit: WikidataHit) {
    if (!selected) return;
    setEntityQid(hit.qid);
    setLoading(true);
    try {
      const superData = await getWikidataSuperclasses(hit.qid);
      const merged = mergeChoices(current.parentChoices, superData.parent_choices ?? []);
      setCurrent((c) => ({ ...c, qid: hit.qid, parentChoices: merged }));
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to fetch P279 parents");
    } finally {
      setLoading(false);
    }
  }

  async function handleWdSearch() {
    if (!selected) return;
    setLoading(true);
    try {
      const data = await searchWikidata(proposalReviewUri(selected), current.wdSearchTerm || selected.label);
      setCurrent((c) => ({ ...c, wikidataHits: data.wikidata_hits }));
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Wikidata search failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleApproveChain() {
    if (!selected || chain.length === 0) return;
    setLoading(true);
    try {
      const entityNode = { qid: entityQid ?? undefined, label: selected.label };
      await approveSubTaxonomy(selected.id, "approve", [entityNode, ...chain]);
      setMsg(`Approved: ${selected.label} → ${chain.map((n) => n.label).join(" → ")}`);
      setSelected(null);
      resetChain();
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approve chain failed");
    } finally {
      setLoading(false);
    }
  }

  async function applyLlmDirect(s: PlacementSuggestion) {
    if (!selected) return;
    try {
      await updateOntologyProposal(proposalReviewUri(selected), { status: "approved", parent_class_uri: s.parent });
      setMsg(`${selected.label} → approved directly under ${extractLabel(s.parent)}`);
      setSelected(null);
      resetChain();
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  async function applyManual(status: "approved" | "rejected") {
    if (!selected) return;
    try {
      if (status === "rejected") {
        await approveSubTaxonomy(selected.id, "reject");
      } else {
        await updateOntologyProposal(proposalReviewUri(selected), {
          status,
          parent_class_uri: status === "approved" ? parentUri : undefined,
        });
      }
      setMsg(`${selected.label} → ${status}`);
      setSelected(null);
      resetChain();
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  async function handleBulkApprove() {
    try {
      const r = await approveOntology();
      setMsg(`Merged ${r.approved_count} class(es) into ontology.ttl`);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approve failed");
    }
  }

  const levelLabel = chain.length > 0
    ? chain[chain.length - 1].label
    : selected?.label ?? "";

  return (
    <>
      <h1 className="page-title">Ontology review</h1>
      {error && <p className="error">{error}</p>}
      {msg && <p className="muted">{msg}</p>}

      <div className="form-row">
        <span className="muted">
          Pending: {summary.pending ?? 0} · Needs typing: {summary.needs_typing ?? 0}
        </span>
        <button type="button" className="primary" onClick={handleBulkApprove}>
          Approve all (merge to ontology.ttl)
        </button>
        <button type="button" onClick={refresh}>Refresh</button>
      </div>

      <div className="split">
        {/* ── Left: proposal list ── */}
        <div className="card table-scroll">
          <h2>Pending proposals</h2>
          <table>
            <thead>
              <tr><th>Label</th><th>Source</th></tr>
            </thead>
            <tbody>
              {pending.length === 0 && (
                <tr><td colSpan={2} className="muted">No pending proposals</td></tr>
              )}
              {pending.map((p) => (
                <tr
                  key={p.id}
                  style={{ cursor: "pointer", background: selected?.id === p.id ? "var(--surface2)" : undefined }}
                  onClick={() => loadProposal(p)}
                >
                  <td>{p.label}</td>
                  <td className="muted">{p.proposed_by || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {needsTyping.length > 0 && (
            <>
              <h2 style={{ marginTop: "1rem" }}>Needs typing</h2>
              <table>
                <thead>
                  <tr><th>Entity</th><th>Source KG</th></tr>
                </thead>
                <tbody>
                  {needsTyping.map((p) => (
                    <tr
                      key={p.id}
                      style={{ cursor: "pointer", background: selected?.id === p.id ? "var(--surface2)" : undefined }}
                      onClick={() => loadProposal(p)}
                    >
                      <td>{p.label}</td>
                      <td className="muted">{(p.source_ttl || "").split("/").pop() || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>

        {/* ── Right: review panel ── */}
        <div className="card panel-detail">
          <h3>{selected ? selected.label : "Select a proposal"}</h3>
          {selected && (
            <>
              <p className="muted" style={{ wordBreak: "break-all", fontSize: "0.8rem" }}>
                {selected.leaf_class_uri || selected.id}
              </p>
              {loading && <p className="muted">Loading…</p>}

              {/* Chain visualization — only once at least one parent chosen */}
              {chain.length > 0 && (
                <ChainViz
                  proposal={selected}
                  entityQid={entityQid}
                  chain={chain}
                  onRollback={rollbackTo}
                  onReset={resetChain}
                />
              )}

              {/* ── Unified proposals section ── */}
              <section style={{ marginTop: chain.length > 0 ? "0.5rem" : "1rem" }}>
                <h4 style={{ margin: "0 0 0.25rem", fontSize: "0.85rem" }}>
                  Select next parent for <em>{levelLabel}</em>
                </h4>

                {/* LLM suggestions */}
                {current.llmProposals.length > 0 && (
                  <ProposalGroup title="LLM suggestions">
                    {current.llmProposals.map((s, i) => (
                      <div key={i} className="suggestion">
                        <div>
                          <strong>{Math.round(s.confidence * 100)}%</strong>
                          {" → "}{extractLabel(s.parent)}
                          <span className="muted" style={{ fontSize: "0.72rem" }}> {s.parent}</span>
                        </div>
                        <div className="muted">{s.reasoning}</div>
                        <div className="form-row" style={{ gap: "0.3rem", marginTop: "0.3rem" }}>
                          <button
                            type="button"
                            onClick={() => selectParent({ label: extractLabel(s.parent), uri: s.parent, source: "llm" })}
                            disabled={loading}
                          >
                            Select ↑
                          </button>
                          <button
                            type="button"
                            className="secondary"
                            style={{ fontSize: "0.72rem" }}
                            onClick={() => applyLlmDirect(s)}
                            disabled={loading}
                            title="Skip chain — approve directly under this class"
                          >
                            Approve directly
                          </button>
                        </div>
                      </div>
                    ))}
                  </ProposalGroup>
                )}

                {/* Wikidata P279 parents */}
                {current.parentChoices.length > 0 && (
                  <ProposalGroup title="Wikidata parents (P279)">
                    {current.parentChoices.map((c) => (
                      <div key={c.qid} className="suggestion">
                        <div>{wikidataTitle(c)}</div>
                        {c.mapped_parent_uri && (
                          <div className="muted" style={{ fontSize: "0.75rem" }}>
                            Maps to: {extractLabel(c.mapped_parent_uri)}
                          </div>
                        )}
                        <button
                          type="button"
                          disabled={loading}
                          onClick={() => selectParent({ qid: c.qid, label: c.label, source: "wikidata" })}
                        >
                          Select ↑
                        </button>
                      </div>
                    ))}
                  </ProposalGroup>
                )}

                {/* Wikidata entity search */}
                <ProposalGroup
                  title={current.qid ? `Wikidata entity linked: ${current.qid}` : "Link Wikidata entity (for more P279 parents)"}
                >
                  <div className="form-row" style={{ marginBottom: "0.4rem" }}>
                    <input
                      type="text"
                      value={current.wdSearchTerm}
                      onChange={(e) => setCurrent((c) => ({ ...c, wdSearchTerm: e.target.value }))}
                      onKeyDown={(e) => e.key === "Enter" && handleWdSearch()}
                      style={{ flex: 1 }}
                    />
                    <button type="button" onClick={handleWdSearch} disabled={loading}>Search</button>
                  </div>
                  {current.wikidataHits.length === 0 && (
                    <p className="muted" style={{ fontSize: "0.78rem" }}>No hits yet — search above.</p>
                  )}
                  {current.wikidataHits.map((h) => (
                    <div
                      key={h.qid}
                      className="suggestion"
                      style={{ borderColor: current.qid === h.qid ? "var(--accent)" : undefined }}
                    >
                      <div>{wikidataTitle(h)}</div>
                      {h.description && <div className="muted">{h.description}</div>}
                      <button
                        type="button"
                        disabled={loading}
                        onClick={() => linkWikidataEntity(h)}
                      >
                        {current.qid === h.qid ? "Linked ✓ — refresh P279" : "Link entity → get P279 parents"}
                      </button>
                    </div>
                  ))}
                </ProposalGroup>
              </section>

              {/* ── Approve chain bar ── */}
              {chain.length > 0 && (
                <div className="chain-approve-bar">
                  <button
                    type="button"
                    className="primary"
                    disabled={loading}
                    onClick={handleApproveChain}
                  >
                    Approve Chain ({chain.length} level{chain.length !== 1 ? "s" : ""})
                  </button>
                  <span className="muted chain-approve-summary">
                    {selected.label} → {chain.map((n) => n.label).join(" → ")}
                  </span>
                </div>
              )}

              {/* ── Manual fallback ── */}
              <section style={{ marginTop: "1rem", borderTop: "1px solid var(--border)", paddingTop: "0.75rem" }}>
                <h4 style={{ margin: "0 0 0.5rem", fontSize: "0.85rem" }}>Manual parent</h4>
                <input
                  type="text"
                  value={parentUri}
                  onChange={(e) => setParentUri(e.target.value)}
                  style={{ width: "100%", marginBottom: "0.5rem" }}
                />
                <div className="form-row">
                  <button type="button" className="primary" onClick={() => applyManual("approved")}>Approve</button>
                  <button type="button" onClick={() => applyManual("rejected")}>Reject</button>
                  <button type="button" onClick={() => loadProposal(selected)}>Refresh</button>
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </>
  );
}
