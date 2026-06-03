import type { PlacementSuggestion, WikidataHit, WikidataParentChoice } from "../api/types";

export interface ChainNode {
  qid?: string;
  label: string;
  uri?: string;
  source: "wikidata" | "llm" | "manual";
}

export interface LevelState {
  label: string;
  qid?: string;
  llmProposals: PlacementSuggestion[];
  wikidataHits: WikidataHit[];
  parentChoices: WikidataParentChoice[];
  wdSearchTerm: string;
}

export interface WikidataChainNode {
  qid: string;
  label: string;
  description?: string;
}
