import type {
  CitationMap,
  DiagnosticResult,
  DiagnosticSubmission,
  PaperResult,
  ResultPage,
  RunDetail,
  RunAudit,
  RunEvent,
  SearchSubmission,
  SourceDescriptor,
} from "./types";

const apiBase = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const code = payload?.error?.code || `http_${response.status}`;
    throw new ApiError(response.status, code);
  }
  return response.json() as Promise<T>;
}

export const api = {
  async sources(): Promise<SourceDescriptor[]> {
    return (await json<{ sources: SourceDescriptor[] }>("/api/v1/sources")).sources;
  },

  diagnostics(payload: DiagnosticSubmission): Promise<DiagnosticResult> {
    return json<DiagnosticResult>("/api/v1/diagnostics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  submit(payload: SearchSubmission, idempotencyKey: string): Promise<RunDetail> {
    return json<RunDetail>("/api/v1/runs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(payload),
    });
  },

  run(runId: string, signal?: AbortSignal): Promise<RunDetail> {
    return json<RunDetail>(`/api/v1/runs/${runId}`, { signal });
  },

  cancel(runId: string, signal?: AbortSignal): Promise<RunDetail> {
    return json<RunDetail>(`/api/v1/runs/${runId}/cancel`, { method: "POST", signal });
  },

  resultPage(runId: string, cursor?: string, signal?: AbortSignal): Promise<ResultPage> {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
    return json<ResultPage>(`/api/v1/runs/${runId}/results${query}`, { signal });
  },

  async results(runId: string, signal?: AbortSignal): Promise<PaperResult[]> {
    return (await this.resultPage(runId, undefined, signal)).results || [];
  },

  citationMap(runId: string, signal?: AbortSignal): Promise<CitationMap> {
    return json<CitationMap>(`/api/v1/runs/${runId}/citation-map`, { signal });
  },

  audit(runId: string, signal?: AbortSignal): Promise<RunAudit> {
    return json<RunAudit>(`/api/v1/runs/${runId}/audit`, { signal });
  },

  async history(cursor?: string, signal?: AbortSignal): Promise<{ items: RunDetail[]; next_cursor: string | null }> {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
    return json<{ items: RunDetail[]; next_cursor?: string | null }>(`/api/v1/history${query}`, { signal }).then(
      (page) => ({ items: page.items || [], next_cursor: page.next_cursor ?? null }),
    );
  },

  deleteHistoryRun(runId: string): Promise<{ run_id: string; status: string }> {
    return json<{ run_id: string; status: string }>(`/api/v1/history/${runId}`, { method: "DELETE" });
  },

  exportUrl(runId: string, format: "csv" | "json"): string {
    return `${apiBase}/api/v1/runs/${runId}/export?format=${format}`;
  },

  logUrl(runId: string): string {
    return `${apiBase}/api/v1/runs/${runId}/logs`;
  },

  async events(
    runId: string,
    afterSequence: number,
    onEvent: (event: RunEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await fetch(`${apiBase}/api/v1/runs/${runId}/events`, {
      headers: {
        Accept: "text/event-stream",
        "Last-Event-ID": String(afterSequence),
      },
      signal,
    });
    if (!response.ok || !response.body) throw new Error(`events_http_${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const lines = frame.split(/\r?\n/);
        const id = lines.find((line) => line.startsWith("id:"))?.slice(3).trim();
        const data = lines
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) {
          const event = JSON.parse(data) as RunEvent;
          if (id !== undefined && Number(id) !== event.sequence) throw new Error("event_cursor_mismatch");
          onEvent(event);
        }
      }
      if (done) break;
    }
  },
};
