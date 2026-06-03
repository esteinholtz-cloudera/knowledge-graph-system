import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, getSubTaxonomy } from "../api/client";
import { TaxonomyChainViz } from "../components/TaxonomyChainViz";
import type { ChainNode } from "./taxonomyTypes";

const STORAGE_PREFIX = "kg-taxonomy-viz:";

export function TaxonomyVisualizer() {
  const { proposalId } = useParams<{ proposalId: string }>();
  const [leafLabel, setLeafLabel] = useState("");
  const [entityQid, setEntityQid] = useState<string | null>(null);
  const [chain, setChain] = useState<ChainNode[]>([]);

  useEffect(() => {
    if (!proposalId) return;
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${proposalId}`);
    if (raw) {
      try {
        const data = JSON.parse(raw) as {
          leafLabel: string;
          entityQid: string | null;
          chain: ChainNode[];
        };
        setLeafLabel(data.leafLabel);
        setEntityQid(data.entityQid);
        setChain(data.chain);
        return;
      } catch {
        /* fall through */
      }
    }
    getSubTaxonomy(proposalId)
      .then((p) => setLeafLabel(p.label))
      .catch((e) => setLeafLabel(e instanceof ApiError ? e.message : "Unknown"));
  }, [proposalId]);

  useEffect(() => {
    const onStorage = (ev: StorageEvent) => {
      if (!proposalId || ev.key !== `${STORAGE_PREFIX}${proposalId}` || !ev.newValue) return;
      try {
        const data = JSON.parse(ev.newValue) as {
          leafLabel: string;
          entityQid: string | null;
          chain: ChainNode[];
        };
        setLeafLabel(data.leafLabel);
        setEntityQid(data.entityQid);
        setChain(data.chain);
      } catch {
        /* ignore */
      }
    };
    window.addEventListener("storage", onStorage);
    const interval = setInterval(() => {
      const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${proposalId}`);
      if (!raw) return;
      try {
        const data = JSON.parse(raw) as {
          leafLabel: string;
          entityQid: string | null;
          chain: ChainNode[];
        };
        setChain(data.chain);
        setEntityQid(data.entityQid);
        setLeafLabel(data.leafLabel);
      } catch {
        /* ignore */
      }
    }, 1500);
    return () => {
      window.removeEventListener("storage", onStorage);
      clearInterval(interval);
    };
  }, [proposalId]);

  return (
    <div className="taxonomy-viz-window" style={{ background: "var(--bg, #0f1117)", color: "var(--text, #e6e8ec)" }}>
      <h1 className="page-title" style={{ fontSize: "1.1rem" }}>
        Taxonomy — {leafLabel || "…"}
      </h1>
      <p className="muted" style={{ fontSize: "0.78rem" }}>
        Live view — edit in the review window; this panel updates automatically.
      </p>
      <TaxonomyChainViz leafLabel={leafLabel} entityQid={entityQid} chain={chain} compact />
    </div>
  );
}

/** Persist chain state for the visualization popup. */
export function syncTaxonomyVisualizer(
  proposalId: string,
  data: { leafLabel: string; entityQid: string | null; chain: ChainNode[] },
) {
  sessionStorage.setItem(`${STORAGE_PREFIX}${proposalId}`, JSON.stringify(data));
}
