export type RunStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "cancelled";

export interface SourceDescriptor {
  id: string;
  label: string;
  api_key?: string;
  status?: string;
}

export interface RunDetail {
  id: string;
  question: string;
  source: string;
  status: RunStatus;
  current_step?: string;
  last_event_sequence?: number;
  result_count?: number;
  error_code?: string;
  warnings?: string[];
  created_at: string;
  finished_at?: string | null;
}

export interface RunEvent {
  run_id: string;
  sequence: number;
  event_type: string;
  stage: string;
  occurred_at: string;
  schema_version: number;
  payload: Record<string, unknown>;
}

export interface PaperResult {
  rank: number;
  title: string;
  authors?: string[];
  authors_text?: string;
  year?: number;
  publish_year?: number;
  venue?: string;
  source?: string;
  abstract?: string;
  score?: number;
  relevance_score?: number;
  reasoning?: string;
  relevance_reason?: string;
  citation_count?: number;
  citations?: string;
  doi?: string;
  url?: string;
  pdf_url?: string;
  provider?: string;
}

export interface CitationNode {
  id: string;
  title: string;
  rank?: number;
  year?: number;
  source?: string;
  citations?: number;
  roles?: string[];
  score?: number;
}

export interface CitationEdge {
  source: string;
  target: string;
  type: string;
}

export interface CitationMap {
  status?: string;
  nodes: CitationNode[];
  edges: CitationEdge[];
}

export interface SearchSubmission {
  question: string;
  source: string;
  search_budget: "fast" | "medium" | "high" | "max";
  field: string;
  citation_enabled: boolean;
  llm: { provider: string; api_type: string; base_url: string; model: string };
  credentials: { llm: { api_key: string }; source: { api_key: string } };
}
