import type {
  AppConfig,
  DocumentRecord,
  Job,
  MarkupLinkResponse,
  OntologyProposal,
  PipelineRequest,
  PrecheckResponse,
  PredicateMapping,
  ProgressEvent,
  SubTaxonomyProposal,
  SuggestPlacementResponse,
  TableData,
  WikidataHit,
  WikidataParentChoice,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api/v1";

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public details?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const errBody = body as { error?: { message?: string; details?: unknown } };
    const msg = errBody?.error?.message || res.statusText;
    throw new ApiError(msg, res.status, errBody?.error?.details);
  }
  return body as T;
}

export function getPrecheck(): Promise<PrecheckResponse> {
  return request("/health/precheck");
}

export function getConfig(): Promise<AppConfig> {
  return request("/config");
}

export function getDocuments(): Promise<{ documents: DocumentRecord[] }> {
  return request("/documents");
}

export function getDocument(id: string): Promise<DocumentRecord> {
  return request(`/documents/${encodeURIComponent(id)}`);
}

export async function uploadDocument(file: File): Promise<{ file_path: string; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/documents/upload`, { method: "POST", body: form });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(
      (body as { error?: { message?: string } })?.error?.message || res.statusText,
      res.status,
    );
  }
  return body;
}

export function startPipeline(body: PipelineRequest): Promise<{ job_id: string }> {
  return request("/jobs/pipeline", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getJob(id: string): Promise<Job> {
  return request(`/jobs/${id}`);
}

export function listJobs(status?: string): Promise<{ jobs: Job[] }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return request(`/jobs${q}`);
}

export function cancelJob(id: string): Promise<{ status: string }> {
  return request(`/jobs/${id}/cancel`, { method: "POST" });
}

export type JobEventHandlers = {
  onProgress: (event: ProgressEvent) => void;
  onDone: (result: Record<string, unknown>) => void;
  onError: (message: string) => void;
  onCancelled?: () => void;
};

export function subscribeJobEvents(jobId: string, handlers: JobEventHandlers): () => void {
  const source = new EventSource(`${API_BASE}/jobs/${jobId}/events`);

  source.addEventListener("progress", (ev) => {
    try {
      handlers.onProgress(JSON.parse(ev.data) as ProgressEvent);
    } catch {
      /* ignore malformed */
    }
  });

  source.addEventListener("done", (ev) => {
    try {
      handlers.onDone(JSON.parse(ev.data) as Record<string, unknown>);
    } catch {
      handlers.onDone({});
    }
    source.close();
  });

  source.addEventListener("job_failed", (ev) => {
    try {
      const data = JSON.parse(ev.data) as { message?: string };
      handlers.onError(data.message || "job failed");
    } catch {
      handlers.onError("job failed");
    }
    source.close();
  });

  source.addEventListener("cancelled", () => {
    handlers.onCancelled?.();
    source.close();
  });

  source.onerror = () => {
    /* EventSource reconnects; terminal state handled by done/error events */
  };

  return () => source.close();
}

export function artifactUrl(documentId: string, kind: "kg" | "markup" | "graph"): string {
  return `${API_BASE}/artifacts/${encodeURIComponent(documentId)}/${kind}`;
}

export function getOntologyStatus(): Promise<{
  summary: Record<string, number>;
  sub_taxonomy_proposals: SubTaxonomyProposal[];
  pending: SubTaxonomyProposal[];
  needs_typing: SubTaxonomyProposal[];
}> {
  return request("/ontology/status");
}

export function listSubTaxonomy(): Promise<{ sub_taxonomy_proposals: SubTaxonomyProposal[]; count: number }> {
  return request("/ontology/sub-taxonomy");
}

export function approveSubTaxonomy(
  proposalId: string,
  action: "approve" | "reject",
  chain?: Array<{ qid?: string; label: string; uri?: string }>,
): Promise<{ action: string; proposal_id: string; merged_classes?: number; entity_retyped?: boolean; already_merged?: boolean }> {
  return request(`/ontology/sub-taxonomy/${encodeURIComponent(proposalId)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, chain }),
  });
}

export function listOntologyProposals(filter?: string): Promise<{ proposals: OntologyProposal[]; count: number }> {
  const q = filter ? `?filter=${encodeURIComponent(filter)}` : "";
  return request(`/ontology/proposals${q}`);
}

export function updateOntologyProposal(
  uri: string,
  body: { status?: string; parent_class_uri?: string; wikidata_id?: string },
): Promise<OntologyProposal> {
  return request(`/ontology/proposals/${encodeURIComponent(uri)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getSubTaxonomy(proposalId: string): Promise<SubTaxonomyProposal> {
  return request(`/ontology/sub-taxonomy/${encodeURIComponent(proposalId)}`);
}

export function getSubTaxonomyMarkupLink(proposalId: string): Promise<MarkupLinkResponse> {
  return request(`/ontology/sub-taxonomy/${encodeURIComponent(proposalId)}/markup-link`);
}

export function diagnoseSubTaxonomy(proposalId: string): Promise<Record<string, unknown>> {
  return request(`/ontology/sub-taxonomy/${encodeURIComponent(proposalId)}/diagnose`);
}

export function suggestPlacement(
  uri: string,
  opts?: {
    searchTerm?: string;
    ancestorChain?: Array<{ qid?: string; label: string; uri?: string; source?: string }>;
  },
): Promise<SuggestPlacementResponse> {
  const body: Record<string, unknown> = {};
  if (opts?.searchTerm) body.search_term = opts.searchTerm;
  if (opts?.ancestorChain?.length) body.ancestor_chain = opts.ancestorChain;
  return request(`/ontology/proposals/${encodeURIComponent(uri)}/suggest-placement`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function searchWikidata(
  uri: string,
  searchTerm?: string,
): Promise<{ search_term: string; wikidata_hits: WikidataHit[]; wikidata_error?: string | null }> {
  return request(`/ontology/proposals/${encodeURIComponent(uri)}/wikidata-search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(searchTerm ? { search_term: searchTerm } : {}),
  });
}

export function selectWikidataEntity(
  uri: string,
  qid: string,
): Promise<{
  selected_qid: string;
  wikidata_parents: WikidataHit[];
  parent_choices: WikidataParentChoice[];
}> {
  return request(`/ontology/proposals/${encodeURIComponent(uri)}/wikidata-select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qid }),
  });
}

export function approveWikidataParent(
  uri: string,
  qid: string,
  label?: string,
): Promise<{ proposal: OntologyProposal; parent_uri: string; new_pending_class?: OntologyProposal }> {
  return request(`/ontology/proposals/${encodeURIComponent(uri)}/wikidata-parent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qid, label }),
  });
}

export function getWikidataSuperclasses(qid: string): Promise<{
  qid: string;
  parents: WikidataHit[];
  parent_choices: WikidataParentChoice[];
}> {
  return request("/ontology/wikidata-superclasses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qid }),
  });
}

export function getWikidataP279Chain(
  qid: string,
  maxDepth = 12,
): Promise<{ qid: string; chain: WikidataHit[]; parent_choices: WikidataParentChoice[] }> {
  return request("/ontology/wikidata-p279-chain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qid, max_depth: maxDepth }),
  });
}

export function approveChain(
  uri: string,
  chain: Array<{ qid?: string; label: string; uri?: string }>,
): Promise<{ approved_count: number; approved: unknown[]; created_pending: unknown[] }> {
  return request(`/ontology/proposals/${encodeURIComponent(uri)}/approve-chain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chain }),
  });
}

export function approveOntology(): Promise<{ approved_count: number }> {
  return request("/ontology/approve", { method: "POST" });
}

export function getNormalizeMap(): Promise<{ mappings: PredicateMapping[] }> {
  return request("/normalize/map");
}

export function updateNormalizeGroup(
  canonical: string,
  body: Partial<PredicateMapping>,
): Promise<PredicateMapping> {
  return request(`/normalize/map/groups/${encodeURIComponent(canonical)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function scanNormalize(noLlm = false): Promise<{ map_path: string; group_count: number; review_count: number }> {
  return request("/normalize/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ no_llm: noLlm }),
  });
}

export function applyNormalize(dryRun: boolean): Promise<{ files: number; triples: number; dry_run: boolean }> {
  return request("/normalize/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dry_run: dryRun }),
  });
}

export function getBenchmarkView(view: "runs" | "chunks" | "llm"): Promise<TableData> {
  return request(`/benchmark/${view}`);
}

export function archiveData(name?: string, llmnamed = false): Promise<{
  archive_path: string;
  paths_updated: number;
  ttl_files_updated: number;
}> {
  return request("/archive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name || null, llmnamed }),
  });
}

export { ApiError };
