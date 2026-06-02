import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  applyNormalize,
  getNormalizeMap,
  scanNormalize,
  updateNormalizeGroup,
} from "../api/client";
import type { PredicateMapping } from "../api/types";

export function Normalize() {
  const [mappings, setMappings] = useState<PredicateMapping[]>([]);
  const [dryRun, setDryRun] = useState(true);
  const [noLlm, setNoLlm] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await getNormalizeMap();
      setMappings(data.mappings || []);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load map");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleScan() {
    setBusy(true);
    try {
      const r = await scanNormalize(noLlm);
      setMsg(`Scan complete: ${r.group_count} groups, ${r.review_count} need review`);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleApply() {
    setBusy(true);
    try {
      const r = await applyNormalize(dryRun);
      setMsg(
        dryRun
          ? `Dry run: would rewrite ${r.triples} triples in ${r.files} files`
          : `Rewrote ${r.triples} triples in ${r.files} files`,
      );
      if (!dryRun) refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Apply failed");
    } finally {
      setBusy(false);
    }
  }

  async function toggleReviewed(m: PredicateMapping, reviewed: boolean) {
    try {
      await updateNormalizeGroup(m.canonical, { reviewed });
      setMappings((prev) =>
        prev.map((row) => (row.canonical === m.canonical ? { ...row, reviewed } : row)),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  async function renameCanonical(m: PredicateMapping) {
    const next = window.prompt("New canonical name:", m.canonical);
    if (!next || next === m.canonical) return;
    try {
      await updateNormalizeGroup(m.canonical, { canonical: next, reviewed: m.reviewed });
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Rename failed");
    }
  }

  const reviewedCount = mappings.filter((m) => m.reviewed).length;

  return (
    <>
      <h1 className="page-title">Predicate normalization</h1>
      {error && <p className="error">{error}</p>}
      {msg && <p className="muted">{msg}</p>}

      <div className="card">
        <div className="form-row">
          <button type="button" disabled={busy} onClick={handleScan}>
            Scan TTL files
          </button>
          <label style={{ flexDirection: "row", alignItems: "center", gap: "0.35rem" }}>
            <input type="checkbox" checked={noLlm} onChange={(e) => setNoLlm(e.target.checked)} />
            No LLM
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: "0.35rem" }}>
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry run
          </label>
          <button type="button" className="primary" disabled={busy} onClick={handleApply}>
            Apply ({reviewedCount} reviewed)
          </button>
          <button type="button" onClick={refresh}>
            Reload map
          </button>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Reviewed</th>
                <th>Canonical</th>
                <th>Variants</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {mappings.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    No mappings — run Scan first
                  </td>
                </tr>
              )}
              {mappings.map((m) => (
                <tr key={m.canonical}>
                  <td>
                    <input
                      type="checkbox"
                      checked={!!m.reviewed}
                      onChange={(e) => toggleReviewed(m, e.target.checked)}
                    />
                  </td>
                  <td>{m.canonical}</td>
                  <td className="muted">{(m.variants || []).join(", ")}</td>
                  <td>
                    <button type="button" onClick={() => renameCanonical(m)}>
                      Rename
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
