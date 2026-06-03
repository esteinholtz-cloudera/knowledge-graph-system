import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  approveSubTaxonomy,
  getSubTaxonomy,
  getWikidataP279Chain,
  getWikidataSuperclasses,
  searchWikidata,
  suggestPlacement,
} from "../api/client";
import type { SubTaxonomyProposal, SuggestPlacementResponse } from "../api/types";
import { TaxonomyChainViz } from "../components/TaxonomyChainViz";
import type { ChainNode, LevelState, WikidataChainNode } from "./taxonomyTypes";
import { syncTaxonomyVisualizer } from "./TaxonomyVisualizer";

function extractLabel(uri: string): string {
  return decodeURIComponent(uri.split(/[/#]/).pop() ?? uri).replace(/_/g, " ");
}

function mergeChoices<T extends { qid: string }>(a: T[], b: T[]): T[] {
  const seen = new Set(a.map((x) => x.qid));
  return [...a, ...b.filter((x) => !seen.has(x.qid))];
}

function emptyLevel(label: string): LevelState {
  return { label, qid: undefined, llmProposals: [], wikidataHits: [], parentChoices: [], wdSearchTerm: label };
}

function formatApiError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const parts = [e.message];
    const d = e.details as { reason?: string; in_pending_list?: boolean; proposal_file?: string } | undefined;
    if (d?.reason) parts.push(`Reason: ${d.reason}`);
    if (d?.in_pending_list === false) {
      parts.push("This id is not in the current pending list — close the tab and reopen from Ontology → Build taxonomy.");
    }
    if (d?.proposal_file) parts.push(`Store: ${d.proposal_file}`);
    return parts.join(" · ");
  }
  return fallback;
}

function proposalReviewUri(p: SubTaxonomyProposal): string {
  return p.leaf_class_uri || p.proposed_classes[0]?.uri || p.id;
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

function ProposalGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="proposal-panel__group">
      <div className="proposals-group-header">{title}</div>
      {children}
    </div>
  );
}

export function TaxonomyReview() {
  const { proposalId } = useParams<{ proposalId: string }>();
  const [proposal, setProposal] = useState<SubTaxonomyProposal | null>(null);
  const [chain, setChain] = useState<ChainNode[]>([]);
  // history[i] = LevelState that was current when chain[i] was selected.
  // Invariant: history.length === chain.length.
  const [history, setHistory] = useState<LevelState[]>([]);
  const [current, setCurrent] = useState<LevelState>(emptyLevel(""));
  const [entityQid, setEntityQid] = useState<string | null>(null);
  const [wdP279Chain, setWdP279Chain] = useState<WikidataChainNode[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  // Focus state — which chain node is selected for mid-chain editing
  const [focusedChainIndex, setFocusedChainIndex] = useState<number | null>(null);
  // LevelState for the focused node's parent-selection level (proposals for what goes above chain[i])
  const [focusedLevel, setFocusedLevel] = useState<LevelState | null>(null);
  // Manual superclass entry
  const [manualLabel, setManualLabel] = useState("");

  // Derived: are we in focused mode?
  const isFocused = focusedChainIndex !== null;
  // The LevelState driving the right panel: focused level or the normal top-of-chain level.
  const activeLevel = isFocused
    ? (focusedLevel ?? emptyLevel(chain[focusedChainIndex]?.label ?? ""))
    : current;

  // Update either `current` or `focusedLevel` depending on mode.
  function setActiveLevel(updater: (prev: LevelState) => LevelState) {
    if (isFocused) {
      setFocusedLevel((fl) => updater(fl ?? emptyLevel(chain[focusedChainIndex!]?.label ?? "")));
    } else {
      setCurrent(updater);
    }
  }

  const reviewUri = proposal ? proposalReviewUri(proposal) : "";
  const levelLabel = chain.length > 0 ? chain[chain.length - 1].label : proposal?.label ?? "";

  useEffect(() => {
    if (!proposalId || !proposal) return;
    syncTaxonomyVisualizer(proposalId, {
      leafLabel: proposal.label,
      entityQid,
      chain,
    });
  }, [proposalId, proposal, entityQid, chain]);

  const buildLevelState = useCallback(
    async (label: string, qid: string | undefined, uri: string, ancestors: ChainNode[]) => {
      const ancestor_chain = [
        ...(entityQid ? [{ qid: entityQid, label: proposal?.label ?? entityQid }] : []),
        ...ancestors.map((n) => ({ qid: n.qid, label: n.label, uri: n.uri, source: n.source })),
      ];
      const [suggest, superData, p279] = await Promise.all([
        suggestPlacement(uri, { searchTerm: label, ancestorChain: ancestor_chain }).catch(
          (): SuggestPlacementResponse => ({
            proposals: [], wikidata_hits: [], wikidata_parents: [], parent_choices: [],
          }),
        ),
        qid
          ? getWikidataSuperclasses(qid).catch(() => ({ qid: "", parents: [], parent_choices: [] }))
          : Promise.resolve({ qid: "", parents: [], parent_choices: [] }),
        qid
          ? getWikidataP279Chain(qid).catch(() => ({ qid: "", chain: [], parent_choices: [] }))
          : Promise.resolve({ qid: "", chain: [], parent_choices: [] }),
      ]);

      const merged = mergeChoices(suggest.parent_choices ?? [], superData.parent_choices ?? []);
      if (p279.chain?.length) {
        setWdP279Chain(p279.chain);
      }
      if (suggest.wikidata_error && !suggest.wikidata_hits?.length) {
        setError(suggest.wikidata_error);
      }
      return {
        label,
        qid: qid ?? suggest.selected_wikidata_qid ?? undefined,
        llmProposals: suggest.proposals ?? [],
        wikidataHits: suggest.wikidata_hits ?? [],
        parentChoices: merged,
        wdSearchTerm: label,
      } satisfies LevelState;
    },
    [entityQid, proposal?.label],
  );

  const loadProposal = useCallback(async () => {
    if (!proposalId) return;
    setLoading(true);
    setError("");
    try {
      const p = await getSubTaxonomy(proposalId);
      setProposal(p);
      setChain([]);
      setHistory([]);
      setEntityQid(null);
      setWdP279Chain([]);
      setFocusedChainIndex(null);
      setFocusedLevel(null);
      setManualLabel("");
      const state = await buildLevelState(p.label, undefined, proposalReviewUri(p), []);
      setCurrent(state);
    } catch (e) {
      setError(formatApiError(e, "Failed to load proposal"));
    } finally {
      setLoading(false);
    }
  }, [proposalId, buildLevelState]);

  useEffect(() => {
    loadProposal();
  }, [loadProposal]);

  function openVisualizer() {
    if (!proposalId) return;
    const url = `${window.location.origin}/ontology/review/${encodeURIComponent(proposalId)}/visualize`;
    window.open(url, `taxonomy-${proposalId}`, "width=480,height=720,scrollbars=yes");
  }

  // Extend the top of the chain with a new parent node (normal, unfocused flow).
  async function selectParent(node: ChainNode) {
    if (!proposal) return;
    setLoading(true);
    try {
      setHistory((h) => [...h, current]);
      const nextChain = [...chain, node];
      setChain(nextChain);
      const nodeUri = node.uri ?? reviewUri;
      const nextState = await buildLevelState(node.label, node.qid, nodeUri, nextChain);
      setCurrent(nextState);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load next level");
    } finally {
      setLoading(false);
    }
  }

  // Extend the chain from a focused mid-chain position: truncates above the focused
  // node, appends the new node, and advances the working level.
  async function selectParentForFocused(node: ChainNode) {
    if (focusedChainIndex === null || !proposal) return;
    const i = focusedChainIndex;
    setLoading(true);
    try {
      // Save the focused level into history so the invariant history.length === chain.length holds.
      const savedLevel = focusedLevel ?? history[i + 1] ?? current;
      const newChain = [...chain.slice(0, i + 1), node];
      const newHistory = [...history.slice(0, i + 1), savedLevel];
      setChain(newChain);
      setHistory(newHistory);
      setFocusedChainIndex(null);
      setFocusedLevel(null);
      const nodeUri = node.uri ?? reviewUri;
      const nextState = await buildLevelState(node.label, node.qid, nodeUri, newChain);
      setCurrent(nextState);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load next level");
    } finally {
      setLoading(false);
    }
  }

  // Unified handler: routes to focused or normal selectParent.
  function handleAddToChain(node: ChainNode) {
    if (isFocused) {
      selectParentForFocused(node);
    } else {
      selectParent(node);
    }
  }

  // Click a chain node to focus it (or toggle focus off if already focused).
  // history[i+1] is the LevelState that was current when chain[i+1] was selected,
  // which is exactly the proposals for chain[i]'s parent — what we want to show.
  function focusChainNode(i: number) {
    if (focusedChainIndex === i) {
      setFocusedChainIndex(null);
      setFocusedLevel(null);
      return;
    }
    setFocusedChainIndex(i);
    const levelState = i === chain.length - 1 ? current : (history[i + 1] ?? null);
    setFocusedLevel(levelState);
    setError("");
    setMsg("");
  }

  // Action d: remove all nodes above the focused node, making it the new top.
  function truncateChainAt(i: number) {
    if (!proposal) return;
    const newCurrent = focusedLevel ?? (i < chain.length - 1 ? history[i + 1] : current) ?? current;
    setChain((c) => c.slice(0, i + 1));
    setHistory((h) => h.slice(0, i + 1));
    setCurrent(newCurrent);
    setFocusedChainIndex(null);
    setFocusedLevel(null);
    setWdP279Chain([]);
    setError("");
    setMsg(`Chain truncated — working above "${chain[i]?.label ?? ""}"`);
  }

  function resetChain() {
    setChain([]);
    setHistory([]);
    setEntityQid(null);
    setWdP279Chain([]);
    setFocusedChainIndex(null);
    setFocusedLevel(null);
    if (proposal) {
      buildLevelState(proposal.label, undefined, reviewUri, []).then(setCurrent);
    }
  }

  // Action b (focused): refresh LLM proposals specifically for the focused node's parent level.
  async function refreshFocusedLlm() {
    if (focusedChainIndex === null || !proposal) return;
    const node = chain[focusedChainIndex];
    setLoading(true);
    try {
      const freshState = await buildLevelState(
        node.label,
        node.qid,
        node.uri ?? reviewUri,
        chain.slice(0, focusedChainIndex + 1),
      );
      setFocusedLevel(freshState);
      setError("");
      setMsg(`LLM suggestions refreshed for "${node.label}"`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to refresh suggestions");
    } finally {
      setLoading(false);
    }
  }

  // Link a Wikidata entity to the LEAF proposal (normal/unfocused mode),
  // refreshing both Wikidata parents and LLM proposals with entity context.
  async function linkWikidataEntity(qid: string, label: string) {
    if (!proposal) return;
    setEntityQid(qid);
    setLoading(true);
    try {
      const entityAncestorChain = [
        { qid, label: proposal.label },
        ...chain.map((n) => ({ qid: n.qid, label: n.label, uri: n.uri, source: n.source })),
      ];
      const [superData, p279, suggest] = await Promise.all([
        getWikidataSuperclasses(qid),
        getWikidataP279Chain(qid),
        suggestPlacement(reviewUri, {
          searchTerm: current.label,
          ancestorChain: entityAncestorChain,
        }).catch((): SuggestPlacementResponse => ({
          proposals: [], wikidata_hits: [], wikidata_parents: [], parent_choices: [],
        })),
      ]);
      setWdP279Chain(p279.chain ?? []);
      setCurrent((c) => ({
        ...c,
        qid,
        llmProposals: suggest.proposals?.length ? suggest.proposals : c.llmProposals,
        parentChoices: mergeChoices(
          mergeChoices(c.parentChoices, superData.parent_choices ?? []),
          suggest.parent_choices ?? [],
        ),
      }));
      setError("");
      setMsg(`Linked ${label} — P279 chain has ${p279.chain?.length ?? 0} levels`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Wikidata lookup failed");
    } finally {
      setLoading(false);
    }
  }

  // Link a Wikidata entity to the FOCUSED node's level (does not change global entityQid).
  async function linkFocusedWikidataEntity(qid: string, label: string) {
    if (!proposal) return;
    setLoading(true);
    try {
      const [superData, p279] = await Promise.all([
        getWikidataSuperclasses(qid),
        getWikidataP279Chain(qid),
      ]);
      setWdP279Chain(p279.chain ?? []);
      setFocusedLevel((fl) => {
        const base = fl ?? emptyLevel(chain[focusedChainIndex!]?.label ?? "");
        return {
          ...base,
          qid,
          parentChoices: mergeChoices(base.parentChoices, superData.parent_choices ?? []),
        };
      });
      setError("");
      setMsg(`Linked ${label} — P279 chain has ${p279.chain?.length ?? 0} levels`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Wikidata lookup failed");
    } finally {
      setLoading(false);
    }
  }

  // Unified handler: routes Wikidata entity linking based on focus mode.
  function handleLinkWikidata(qid: string, label: string) {
    if (isFocused) {
      linkFocusedWikidataEntity(qid, label);
    } else {
      linkWikidataEntity(qid, label);
    }
  }

  // Wikidata entity search — updates `activeLevel.wikidataHits` regardless of focus mode.
  async function handleWdSearch() {
    if (!proposal) return;
    setLoading(true);
    try {
      const data = await searchWikidata(reviewUri, activeLevel.wdSearchTerm || proposal.label);
      setActiveLevel((c) => ({ ...c, wikidataHits: data.wikidata_hits }));
      if (data.wikidata_error) {
        setError(data.wikidata_error);
      } else if (data.wikidata_hits.length === 0) {
        setError("No Wikidata matches for that search term.");
      } else {
        setError("");
        setMsg(`Found ${data.wikidata_hits.length} Wikidata match(es)`);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Wikidata search failed");
    } finally {
      setLoading(false);
    }
  }

  // Action c: add a manually typed class label as a chain node.
  function addManualParent() {
    const label = manualLabel.trim();
    if (!label) return;
    handleAddToChain({ label, source: "manual" });
    setManualLabel("");
  }

  function applyWikidataP279Chain() {
    if (wdP279Chain.length < 2) return;
    const parents: ChainNode[] = wdP279Chain.slice(1).map((n) => ({
      qid: n.qid,
      label: n.label,
      source: "wikidata" as const,
    }));
    setMsg(`Applied Wikidata P279 chain (${parents.length} superclasses)`);

    if (isFocused && focusedChainIndex !== null) {
      // Attach the P279 ancestors above the focused node instead of replacing the full chain.
      const base = chain.slice(0, focusedChainIndex + 1);
      const savedLevel = focusedLevel ?? history[focusedChainIndex + 1] ?? current;
      const newChain = [...base, ...parents];
      const newHistory = [...history.slice(0, focusedChainIndex + 1), savedLevel];
      setChain(newChain);
      setHistory(newHistory);
      setFocusedChainIndex(null);
      setFocusedLevel(null);
      if (parents.length > 0) {
        const top = parents[parents.length - 1];
        buildLevelState(top.label, top.qid, reviewUri, newChain).then(setCurrent);
      }
    } else {
      setChain(parents);
      setHistory([]);
      if (parents.length > 0) {
        const top = parents[parents.length - 1];
        buildLevelState(top.label, top.qid, reviewUri, parents).then(setCurrent);
      }
    }
  }

  async function handleApproveChain() {
    if (!proposal || chain.length === 0) return;
    setLoading(true);
    try {
      const entityNode = { qid: entityQid ?? undefined, label: proposal.label };
      const result = await approveSubTaxonomy(proposal.id, "approve", [entityNode, ...chain]);
      if (result.already_merged) {
        setMsg(`${proposal.label} was already approved and merged — closing.`);
      } else {
        setMsg(`Approved chain for ${proposal.label}`);
      }
      window.close();
    } catch (e) {
      setError(formatApiError(e, "Approve chain failed"));
    } finally {
      setLoading(false);
    }
  }

  if (!proposalId) {
    return <p className="error">Missing proposal id</p>;
  }

  const focusedNode = focusedChainIndex !== null ? chain[focusedChainIndex] : null;
  const activeLevelLabel = focusedNode?.label ?? levelLabel;

  return (
    <div className="taxonomy-review-page">
      <header className="taxonomy-review-header">
        <div>
          <Link to="/ontology" className="muted">← Ontology list</Link>
          <h1 className="page-title" style={{ margin: "0.25rem 0 0" }}>
            {proposal?.label ?? "Taxonomy review"}
          </h1>
        </div>
        <div className="form-row">
          <button type="button" onClick={openVisualizer} disabled={!proposal}>
            Open visualization window
          </button>
          <button type="button" onClick={loadProposal} disabled={loading}>
            Refresh
          </button>
        </div>
      </header>

      <div className="taxonomy-review-status">
        {error && <p className="error">{error}</p>}
        {msg && <p className="muted taxonomy-review-msg">{msg}</p>}
        {loading && <p className="muted">Loading…</p>}
      </div>

      {proposal && (
        <div className="taxonomy-review-grid">
          <aside className="card taxonomy-review-chain-panel">
            <TaxonomyChainViz
              leafLabel={proposal.label}
              entityQid={entityQid}
              chain={chain}
              focusedIndex={focusedChainIndex}
              onFocus={focusChainNode}
              onReset={resetChain}
            />
            {chain.length > 0 && !isFocused && (
              <div className="chain-approve-bar" style={{ marginTop: "0.75rem" }}>
                <button type="button" className="primary" disabled={loading} onClick={handleApproveChain}>
                  Approve Chain ({chain.length} level{chain.length !== 1 ? "s" : ""})
                </button>
              </div>
            )}
            {wdP279Chain.length > 1 && (
              <div className="wd-p279-chain-panel">
                <div className="proposals-group-header">Wikidata P279 (full chain)</div>
                <ol className="wd-p279-list">
                  {wdP279Chain.map((n, i) => (
                    <li key={n.qid}>
                      {i === 0 ? "≡ " : "↑ "}
                      {wikidataTitle(n)}
                    </li>
                  ))}
                </ol>
                <button type="button" className="primary" style={{ width: "100%" }} onClick={applyWikidataP279Chain}>
                  {isFocused ? "Attach P279 chain above focused node" : "Use full P279 chain"}
                </button>
              </div>
            )}
          </aside>

          <main className="card proposal-panel">
            {/* Panel header — focused vs normal mode */}
            {isFocused ? (
              <div className="proposal-panel__focused-header">
                <div>
                  <h2 style={{ margin: "0 0 0.25rem", fontSize: "1rem" }}>
                    Find superclass for: <em>{focusedNode!.label}</em>
                  </h2>
                  <p className="muted" style={{ fontSize: "0.8rem" }}>
                    Selecting a parent replaces everything above <em>{focusedNode!.label}</em>.
                  </p>
                </div>
                <div className="form-row" style={{ flexShrink: 0 }}>
                  <button
                    type="button"
                    title="Remove all chain nodes above this one"
                    disabled={loading}
                    onClick={() => truncateChainAt(focusedChainIndex!)}
                  >
                    ✂ Truncate here
                  </button>
                  <button
                    type="button"
                    onClick={() => { setFocusedChainIndex(null); setFocusedLevel(null); }}
                  >
                    ← Unfocus
                  </button>
                </div>
              </div>
            ) : (
              <>
                <h2 style={{ margin: "0 0 0.5rem", fontSize: "1rem" }}>
                  Step: choose superclass for <em>{activeLevelLabel}</em>
                </h2>
                <p className="muted" style={{ fontSize: "0.8rem" }}>
                  LLM and Wikidata run in parallel. Pick one parent per level; the chain builds upward.
                  Click any chain node to focus it and edit from that position.
                </p>
              </>
            )}

            <div className="proposal-panel__columns">
              {/* ── LLM proposals ── */}
              <ProposalGroup title="LLM superclass suggestions">
                {isFocused && (
                  <button
                    type="button"
                    disabled={loading}
                    style={{ width: "100%", marginBottom: "0.5rem" }}
                    onClick={refreshFocusedLlm}
                  >
                    ↺ Refresh LLM suggestions
                  </button>
                )}
                {activeLevel.llmProposals.length === 0 && (
                  <p className="muted">
                    {isFocused ? "No suggestions — press Refresh LLM." : "No LLM suggestions."}
                  </p>
                )}
                {activeLevel.llmProposals.map((s, i) => (
                  <div key={i} className="suggestion">
                    <div>
                      <strong>{Math.round(s.confidence * 100)}%</strong> → {extractLabel(s.parent)}
                    </div>
                    <div className="muted">{s.reasoning}</div>
                    <button
                      type="button"
                      disabled={loading}
                      onClick={() => handleAddToChain({ label: extractLabel(s.parent), uri: s.parent, source: "llm" })}
                    >
                      Add to chain ↑
                    </button>
                  </div>
                ))}
              </ProposalGroup>

              {/* ── Wikidata ── */}
              <ProposalGroup title="Wikidata (entity + P279 parents)">
                <div className="form-row wikidata-search-row">
                  <input
                    type="text"
                    value={activeLevel.wdSearchTerm}
                    onChange={(e) => setActiveLevel((c) => ({ ...c, wdSearchTerm: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && handleWdSearch()}
                    style={{ flex: 1 }}
                    placeholder="Search Wikidata…"
                  />
                  <button type="button" onClick={handleWdSearch} disabled={loading}>
                    Search
                  </button>
                </div>
                {activeLevel.wikidataHits.length > 0 && (
                  <div className="wikidata-hits-grid">
                    {activeLevel.wikidataHits.map((h) => (
                      <div key={h.qid} className="suggestion">
                        <div>{wikidataTitle(h)}</div>
                        {h.description && <div className="muted">{h.description}</div>}
                        <button
                          type="button"
                          disabled={loading}
                          onClick={() => handleLinkWikidata(h.qid, h.label)}
                        >
                          Link &amp; load P279 chain
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {activeLevel.parentChoices.length === 0 && activeLevel.wikidataHits.length === 0 && (
                  <p className="muted">Search to link a Wikidata entity, then pick a P279 parent.</p>
                )}
                {activeLevel.parentChoices.map((c) => (
                  <div key={c.qid} className="suggestion">
                    <div>{wikidataTitle(c)}</div>
                    <button
                      type="button"
                      disabled={loading}
                      onClick={() => handleAddToChain({ qid: c.qid, label: c.label, source: "wikidata" })}
                    >
                      Add to chain ↑
                    </button>
                  </div>
                ))}
              </ProposalGroup>
            </div>

            {/* ── Manual entry (action c) ── */}
            <div className="proposal-panel__manual">
              <div className="proposals-group-header">Manual entry</div>
              <div className="form-row">
                <input
                  type="text"
                  value={manualLabel}
                  onChange={(e) => setManualLabel(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addManualParent()}
                  placeholder="Type a class label and press Enter or Add…"
                  style={{ flex: 1 }}
                />
                <button type="button" disabled={loading || !manualLabel.trim()} onClick={addManualParent}>
                  Add ↑
                </button>
              </div>
            </div>

            {/* Approve button at bottom of panel when chain is non-empty */}
            {chain.length > 0 && isFocused && (
              <div style={{ marginTop: "0.75rem", borderTop: "1px solid var(--border)", paddingTop: "0.75rem" }}>
                <button type="button" className="primary" disabled={loading} onClick={handleApproveChain}>
                  Approve Chain ({chain.length} level{chain.length !== 1 ? "s" : ""})
                </button>
              </div>
            )}
          </main>
        </div>
      )}
    </div>
  );
}
