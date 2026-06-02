import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  archiveData,
  artifactUrl,
  getDocuments,
  getPrecheck,
  listJobs,
} from "../api/client";
import type { DocumentRecord, Job } from "../api/types";

export function Dashboard() {
  const [precheckOk, setPrecheckOk] = useState<boolean | null>(null);
  const [precheckDetail, setPrecheckDetail] = useState<string>("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [error, setError] = useState("");
  const [archiveMsg, setArchiveMsg] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [pc, jobList, docs] = await Promise.all([
        getPrecheck(),
        listJobs(),
        getDocuments(),
      ]);
      setPrecheckOk(pc.ok);
      setPrecheckDetail(
        pc.checks
          .map((c) => `${c.name}: ${c.message}`)
          .join(" · ") || (pc.ok ? "All checks passed" : "Checks failed"),
      );
      setJobs(jobList.jobs.slice(0, 20));
      setDocuments(docs.documents);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load dashboard");
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 5000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function handleArchive() {
    if (!window.confirm("Archive data/ and reset workspace?")) return;
    try {
      const r = await archiveData();
      setArchiveMsg(`Archived to ${r.archive_path}`);
      refresh();
    } catch (e) {
      setArchiveMsg(e instanceof ApiError ? e.message : "Archive failed");
    }
  }

  return (
    <>
      <h1 className="page-title">Dashboard</h1>
      {error && <p className="error">{error}</p>}

      <div className="stack">
        <div className="card">
          <h2>Pre-flight</h2>
          {precheckOk === null ? (
            <p className="muted">Checking…</p>
          ) : (
            <>
              <span className={`badge ${precheckOk ? "ok" : "err"}`}>
                {precheckOk ? "Ready" : "Not ready"}
              </span>
              <p className="muted" style={{ marginTop: "0.5rem" }}>
                {precheckDetail}
              </p>
            </>
          )}
        </div>

        <div className="grid-2">
          <div className="card">
            <h2>Recent jobs</h2>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Type</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.length === 0 && (
                    <tr>
                      <td colSpan={3} className="muted">
                        No jobs yet
                      </td>
                    </tr>
                  )}
                  {jobs.map((j) => (
                    <tr key={j.id}>
                      <td>
                        <span className={`badge ${j.status === "succeeded" ? "ok" : "neutral"}`}>
                          {j.status}
                        </span>
                      </td>
                      <td>{j.type}</td>
                      <td className="muted">{new Date(j.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h2>Documents</h2>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Artifacts</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.length === 0 && (
                    <tr>
                      <td colSpan={2} className="muted">
                        No documents processed
                      </td>
                    </tr>
                  )}
                  {documents.map((d) => {
                    const id = d.id || (d.filename as string) || "unknown";
                    return (
                      <tr key={id}>
                        <td>{id}</td>
                        <td>
                          <a href={artifactUrl(id, "kg")} target="_blank" rel="noreferrer">
                            TTL
                          </a>
                          {" · "}
                          <a href={artifactUrl(id, "markup")} target="_blank" rel="noreferrer">
                            Markup
                          </a>
                          {" · "}
                          <a href={artifactUrl(id, "graph")} target="_blank" rel="noreferrer">
                            Graph
                          </a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>Admin</h2>
          <button type="button" onClick={handleArchive}>
            Archive data/
          </button>
          {archiveMsg && <p className="muted" style={{ marginTop: "0.5rem" }}>{archiveMsg}</p>}
        </div>
      </div>
    </>
  );
}
