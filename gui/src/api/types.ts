export interface ProgressEvent {
  job_id?: string;
  stage: string;
  chunk?: number | null;
  total_chunks?: number | null;
  message?: string;
  percent?: number | null;
  payload?: Record<string, unknown>;
}

export interface Job {
  id: string;
  type: string;
  status: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  params: Record<string, unknown>;
  result?: PipelineResult | null;
  error?: string | null;
}

export interface PipelineResult {
  document_id: string;
  kg_path: string;
  markup_path: string;
  graph_path?: string | null;
  entity_count: number;
  triple_count: number;
  proposals: unknown[];
}

export interface PipelineRequest {
  file_path: string;
  output_dir?: string;
  max_chunks?: number | null;
  with_graph?: boolean;
  domain?: string;
  skip_precheck?: boolean;
}

export interface PrecheckResponse {
  ok: boolean;
  checks: Array<Record<string, unknown>>;
}

export interface AppConfig {
  llm: Record<string, unknown>;
  document: Record<string, unknown>;
  entity_resolution: Record<string, unknown>;
  pipeline: { max_concurrent_llm_calls?: number };
  domains: string[];
}

export interface DocumentRecord {
  id: string;
  filename?: string;
  kg_path?: string;
  artifacts?: {
    kg?: string | null;
    markup?: string | null;
    graph?: string | null;
  };
  [key: string]: unknown;
}

export interface ProposedClass {
  uri: string;
  label: string;
  comment?: string;
  subclass_of?: string[];
  equivalent_class?: string[];
  is_new_root?: boolean;
  status?: string;
}

export interface SubclassLink {
  child_uri: string;
  parent_uri: string;
  source?: string;
}

export interface SubTaxonomyProposal {
  id: string;
  status: string;
  label: string;
  is_needs_typing?: boolean;
  proposed_classes: ProposedClass[];
  subclass_links: SubclassLink[];
  leaf_class_uri: string;
  entity_uri?: string | null;
  source_ttl?: string | null;
  proposed_by?: string;
  created_at?: string;
}

/** @deprecated use SubTaxonomyProposal — kept for transitional typing */
export interface OntologyProposal {
  id?: string;
  uri?: string;
  label: string;
  comment?: string;
  status?: string;
  proposed_by?: string;
  subclass_of?: string[];
  equivalent_class?: string[];
  node?: string;
  entity_uri?: string;
  leaf_class_uri?: string;
  is_needs_typing?: boolean;
  proposed_classes?: ProposedClass[];
}

export interface PlacementSuggestion {
  parent: string;
  confidence: number;
  reasoning: string;
}

export interface WikidataHit {
  qid: string;
  label: string;
  description?: string;
}

export interface WikidataParentChoice {
  qid: string;
  label: string;
  mapped_parent_uri?: string | null;
}

export interface SuggestPlacementResponse {
  proposals: PlacementSuggestion[];
  wikidata_hits: WikidataHit[];
  wikidata_parents: WikidataHit[];
  parent_choices?: WikidataParentChoice[];
  selected_wikidata_qid?: string | null;
}

export interface PredicateMapping {
  canonical: string;
  variants: string[];
  reviewed?: boolean;
  total_uses?: number;
  reason?: string;
}

export interface TableData {
  columns: string[];
  rows: unknown[][];
}
