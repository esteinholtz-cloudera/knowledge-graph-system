import { Fragment } from "react";
import type { ChainNode } from "../pages/taxonomyTypes";

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

export function TaxonomyChainViz({
  leafLabel,
  entityQid,
  chain,
  focusedIndex,
  onFocus,
  onReset,
  compact = false,
}: {
  leafLabel: string;
  entityQid: string | null;
  chain: ChainNode[];
  focusedIndex?: number | null;
  onFocus?: (index: number) => void;
  onReset?: () => void;
  compact?: boolean;
}) {
  return (
    <div className={`chain-viz ${compact ? "chain-viz--compact" : ""}`}>
      <div className="chain-viz__header">
        <span className="chain-viz__title">Taxonomy proposal</span>
        {onReset && (
          <button type="button" className="chain-viz__reset" onClick={onReset}>
            ✕ reset chain
          </button>
        )}
      </div>
      <div className="chain-viz__body">
        <div className="chain-node chain-node--proposal">
          {leafLabel}
          <span className="chain-tag">leaf</span>
        </div>
        {entityQid && (
          <>
            <div className="chain-arrow">≡ owl:equivalentClass</div>
            <div className="chain-node chain-node--entity">{wikidataTitle({ qid: entityQid, label: entityQid })}</div>
          </>
        )}
        {chain.map((node, i) => {
          const isFocused = focusedIndex === i;
          const isAboveFocused = focusedIndex !== null && focusedIndex !== undefined && i > focusedIndex;
          const nodeClasses = [
            "chain-node",
            onFocus ? "chain-node--clickable" : "",
            isFocused ? "chain-node--focused" : "",
            isAboveFocused ? "chain-node--above-focused" : "",
            i === chain.length - 1 && !isFocused ? "chain-node--current" : "",
            i < chain.length - 1 && !isFocused ? "chain-node--ancestor" : "",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <Fragment key={`${node.qid ?? node.uri ?? node.label}-${i}`}>
              <div className="chain-arrow">↑ rdfs:subClassOf</div>
              {onFocus ? (
                <button
                  type="button"
                  className={nodeClasses}
                  title={isFocused ? "Click to unfocus" : "Click to focus this node"}
                  onClick={() => onFocus(i)}
                >
                  {node.qid ? wikidataTitle(node as { qid: string; label: string }) : <strong>{node.label}</strong>}
                  <span className="chain-tag">{node.source}</span>
                  {isFocused && <span className="chain-tag chain-tag--focused">focused</span>}
                </button>
              ) : (
                <div className={nodeClasses}>
                  {node.qid ? wikidataTitle(node as { qid: string; label: string }) : <strong>{node.label}</strong>}
                  <span className="chain-tag">{node.source}</span>
                </div>
              )}
            </Fragment>
          );
        })}
        <div className="chain-arrow chain-arrow--pending">↑ select next superclass…</div>
      </div>
    </div>
  );
}
