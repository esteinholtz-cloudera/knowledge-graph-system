import { useEffect, useState } from "react";
import { ApiError, getBenchmarkView } from "../api/client";
import type { TableData } from "../api/types";

type View = "runs" | "chunks" | "llm";

export function Benchmark() {
  const [view, setView] = useState<View>("runs");
  const [table, setTable] = useState<TableData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    getBenchmarkView(view)
      .then(setTable)
      .catch((e) => {
        setTable(null);
        setError(e instanceof ApiError ? e.message : "Failed to load benchmark");
      });
  }, [view]);

  return (
    <>
      <h1 className="page-title">Benchmark</h1>
      {error && <p className="error">{error}</p>}

      <div className="tabs">
        {(["runs", "chunks", "llm"] as View[]).map((v) => (
          <button
            key={v}
            type="button"
            className={view === v ? "active" : ""}
            onClick={() => setView(v)}
          >
            {v}
          </button>
        ))}
      </div>

      <div className="card table-scroll">
        {!table ? (
          <p className="muted">Loading…</p>
        ) : table.rows.length === 0 ? (
          <p className="muted">No data (install benchmark extra: uv sync --extra benchmark)</p>
        ) : (
          <table>
            <thead>
              <tr>
                {table.columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>{String(cell ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
