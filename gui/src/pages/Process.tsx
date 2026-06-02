import { useEffect, useState } from "react";
import {
  ApiError,
  artifactUrl,
  cancelJob,
  getConfig,
  startPipeline,
  subscribeJobEvents,
  uploadDocument,
} from "../api/client";
import type { PipelineResult, ProgressEvent } from "../api/types";

function progressPercent(events: ProgressEvent[]): number {
  const last = [...events].reverse().find((e) => e.chunk && e.total_chunks);
  if (!last?.chunk || !last.total_chunks) return 0;
  return Math.round((last.chunk / last.total_chunks) * 100);
}

export function Process() {
  const [domains, setDomains] = useState<string[]>(["default"]);
  const [domain, setDomain] = useState("default");
  const [maxChunks, setMaxChunks] = useState("");
  const [withGraph, setWithGraph] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getConfig()
      .then((c) => setDomains(c.domains.length ? c.domains : ["default"]))
      .catch(() => {});
  }, []);

  async function handleStart() {
    if (!file) {
      setError("Choose a file first");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    setEvents([]);
    setStatus("uploading");

    try {
      const uploaded = await uploadDocument(file);
      setStatus("starting pipeline");
      const { job_id } = await startPipeline({
        file_path: uploaded.file_path,
        domain,
        max_chunks: maxChunks ? parseInt(maxChunks, 10) : null,
        with_graph: withGraph,
      });
      setJobId(job_id);
      setStatus("running");

      subscribeJobEvents(job_id, {
        onProgress: (ev) => {
          setEvents((prev) => [...prev, ev]);
          setStatus(ev.stage);
        },
        onDone: (res) => {
          setResult(res as unknown as PipelineResult);
          setStatus("succeeded");
          setBusy(false);
        },
        onError: (msg) => {
          setError(msg);
          setStatus("failed");
          setBusy(false);
        },
        onCancelled: () => {
          setStatus("cancelled");
          setBusy(false);
        },
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to start");
      setStatus("");
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (!jobId) return;
    try {
      await cancelJob(jobId);
      setStatus("cancel requested");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Cancel failed");
    }
  }

  const pct = progressPercent(events);
  const docId = result?.document_id;

  return (
    <>
      <h1 className="page-title">Process document</h1>
      {error && <p className="error">{error}</p>}

      <div className="card stack">
        <div className="form-row">
          <label>
            File
            <input
              type="file"
              accept=".txt,.md,.markdown,.pdf,.docx,.doc"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <label>
            Domain
            <select value={domain} onChange={(e) => setDomain(e.target.value)}>
              {domains.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label>
            Max chunks
            <input
              type="number"
              min={1}
              placeholder="all"
              value={maxChunks}
              onChange={(e) => setMaxChunks(e.target.value)}
            />
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: "0.35rem" }}>
            <input
              type="checkbox"
              checked={withGraph}
              onChange={(e) => setWithGraph(e.target.checked)}
            />
            Generate graph HTML
          </label>
        </div>

        <div className="form-row">
          <button type="button" className="primary" disabled={busy} onClick={handleStart}>
            {busy ? "Running…" : "Start pipeline"}
          </button>
          {jobId && busy && (
            <button type="button" onClick={handleCancel}>
              Cancel
            </button>
          )}
        </div>

        {status && (
          <>
            <p>
              Status: <span className="badge neutral">{status}</span>
              {jobId && <span className="muted"> · {jobId.slice(0, 8)}…</span>}
            </p>
            {busy && (
              <>
                <div className="progress-bar">
                  <div style={{ width: `${pct}%` }} />
                </div>
                <p className="muted">{pct}% (by chunk progress)</p>
              </>
            )}
            <div className="log">
              {events.slice(-30).map((ev, i) => (
                <div key={i}>
                  [{ev.stage}]
                  {ev.chunk != null && ` ${ev.chunk}/${ev.total_chunks}`}
                  {ev.message ? ` ${ev.message}` : ""}
                </div>
              ))}
            </div>
          </>
        )}

        {result && docId && (
          <div className="card" style={{ marginTop: "0.5rem" }}>
            <h2>Complete</h2>
            <p>
              {result.entity_count} entities · {result.triple_count} triples
            </p>
            <p>
              <a href={artifactUrl(docId, "kg")} target="_blank" rel="noreferrer">
                Download TTL
              </a>
              {" · "}
              <a href={artifactUrl(docId, "markup")} target="_blank" rel="noreferrer">
                HTML markup
              </a>
              {result.graph_path && (
                <>
                  {" · "}
                  <a href={artifactUrl(docId, "graph")} target="_blank" rel="noreferrer">
                    Graph
                  </a>
                </>
              )}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
