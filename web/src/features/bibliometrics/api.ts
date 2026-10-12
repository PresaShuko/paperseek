import { download, json } from "../../api/client";
import type { components } from "../../api/generated";

type Schema = components["schemas"];
export type Analysis = Schema["AnalysisDetail"];
export type AnalysisPage = Schema["AnalysisPage"];
export type MetricNetwork = Schema["MetricNetwork"];
export type NetworkRequest = Schema["NetworkRequest"];
export type MetricBucket = Schema["MetricBucket"];
const root = "/api/v1/bibliometrics";
const send = (method: string, value: unknown, key?: string) => ({
  method,
  headers: {
    "Content-Type": "application/json",
    ...(key ? { "Idempotency-Key": key } : {}),
  },
  body: JSON.stringify(value),
});
export const metricsApi = {
  create: (source_run_id: string, key: string) =>
    json<Analysis>(root, send("POST", { source_run_id }, key)),
  list: (q = "", offset = 0, signal?: AbortSignal) =>
    json<AnalysisPage>(
      `${root}?${new URLSearchParams({ q, offset: String(offset) })}`,
      { signal },
    ),
  get: (id: string, signal?: AbortSignal) =>
    json<Analysis>(`${root}/${id}`, { signal }),
  rename: (id: string, title: string) =>
    json<void>(`${root}/${id}`, send("PATCH", { title })),
  remove: (id: string) => json<void>(`${root}/${id}`, { method: "DELETE" }),
  network: (id: string, request: NetworkRequest, signal?: AbortSignal) =>
    json<MetricNetwork>(`${root}/${id}/network`, {
      ...send("POST", request),
      signal,
    }),
  export: (id: string, format: "csv" | "json") =>
    download(
      `${root}/${id}/export?format=${format}`,
      `bibliometrics.${format}`,
    ),
};
