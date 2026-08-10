import type {
  CitationMap,
  PaperResult,
  RunDetail,
  RunEvent,
  SearchSubmission,
  SourceDescriptor,
} from "./types";

const apiBase = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const code = payload?.error?.code || `http_${response.status}`;
    throw new Error(code);
  }
  return response.json() as Promise<T>;
}

export const api = {
  async sources(): Promise<SourceDescriptor[]> {
    return (await json<{ sources: SourceDescriptor[] }>("/api/v1/sources")).sources;
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

  run(runId: string): Promise<RunDetail> {
    return json<RunDetail>(`/api/v1/runs/${runId}`);
  },

  async results(runId: string): Promise<PaperResult[]> {
    return (await json<{ results: PaperResult[] }>(`/api/v1/runs/${runId}/results`)).results;
  },

  citationMap(runId: string): Promise<CitationMap> {
    return json<CitationMap>(`/api/v1/runs/${runId}/citation-map`);
  },

  async history(): Promise<RunDetail[]> {
    return (await json<{ items: RunDetail[] }>("/api/v1/history")).items;
  },

  exportUrl(runId: string, format: "csv" | "json"): string {
    return `${apiBase}/api/v1/runs/${runId}/export?format=${format}`;
  },

  async events(runId: string, onEvent: (event: RunEvent) => void): Promise<void> {
    const response = await fetch(`${apiBase}/api/v1/runs/${runId}/events`, {
      headers: { Accept: "text/event-stream" },
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
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) onEvent(JSON.parse(data) as RunEvent);
      }
      if (done) break;
    }
  },
};
