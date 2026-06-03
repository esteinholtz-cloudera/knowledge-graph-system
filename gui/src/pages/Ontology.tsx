import { useCallback, useEffect, useState } from "react";
import { ApiError, approveOntology, getOntologyStatus } from "../api/client";
import type { SubTaxonomyProposal } from "../api/types";

function openTaxonomyReview(proposalId: string) {
  const url = `${window.location.origin}/ontology/review/${encodeURIComponent(proposalId)}`;
  window.open(url, `taxonomy-review-${proposalId}`, "width=1400,height=920,scrollbars=yes");
}

function ProposalTable({
  title,
  rows,
  selectedId,
  onSelect,
  sourceCol,
}: {
  title: string;
  rows: SubTaxonomyProposal[];
  selectedId: string | null;
  onSelect: (p: SubTaxonomyProposal) => void;
  sourceCol: (p: SubTaxonomyProposal) => string;
}) {
  return (
    <>
      <h2>{title}</h2>
      <table>
        <thead>
          <tr>
            <th>Label</th>
            <th>Source</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={3} className="muted">
                None
              </td>
            </tr>
          )}
          {rows.map((p) => (
            <tr
              key={p.id}
              style={{
                cursor: "pointer",
                background: selectedId === p.id ? "var(--surface2)" : undefined,
              }}
              onClick={() => onSelect(p)}
            >
              <td>{p.label}</td>
              <td className="muted">{sourceCol(p)}</td>
              <td>
                <button
                  type="button"
                  className="primary"
                  style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    openTaxonomyReview(p.id);
                  }}
                >
                  Build taxonomy…
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function Ontology() {
  const [pending, setPending] = useState<SubTaxonomyProposal[]>([]);
  const [needsTyping, setNeedsTyping] = useState<SubTaxonomyProposal[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

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

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleBulkApprove() {
    try {
      const r = await approveOntology();
      setMsg(`Merged ${r.approved_count} class(es) into ontology.ttl`);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approve failed");
    }
  }

  return (
    <>
      <h1 className="page-title">Ontology review</h1>
      <p className="muted" style={{ maxWidth: "42rem" }}>
        Select a proposal and open <strong>Build taxonomy</strong> to place it interactively: LLM superclass
        suggestions and recursive Wikidata P279 lookup run in parallel at each level. The taxonomy chain
        can be viewed in a separate window.
      </p>
      {error && <p className="error">{error}</p>}
      {msg && <p className="muted">{msg}</p>}

      <div className="form-row">
        <span className="muted">
          New classes: {summary.pending ?? pending.length} · Needs typing: {summary.needs_typing ?? needsTyping.length}
        </span>
        <button type="button" className="primary" onClick={handleBulkApprove}>
          Approve all (merge to ontology.ttl)
        </button>
        <button type="button" onClick={refresh}>
          Refresh
        </button>
      </div>

      <div className="card table-scroll">
        <ProposalTable
          title={`New class proposals (${pending.length})`}
          rows={pending}
          selectedId={selectedId}
          onSelect={(p) => setSelectedId(p.id)}
          sourceCol={(p) => p.proposed_by || "—"}
        />
        {needsTyping.length > 0 && (
          <ProposalTable
            title={`Needs typing (${needsTyping.length})`}
            rows={needsTyping}
            selectedId={selectedId}
            onSelect={(p) => setSelectedId(p.id)}
            sourceCol={(p) => (p.source_ttl || "").split("/").pop() || "—"}
          />
        )}
      </div>
    </>
  );
}
