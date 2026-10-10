import { api, download } from "../../api/client";
import { metricsApi } from "../bibliometrics/api";
import { reviewApi, saveDownload } from "../review/api";
import type { WorkspaceModule } from "./state";

export interface HistoryRecord {
  id: string;
  title: string;
  path: string;
  date: string;
  count: number;
  status: string;
  active: boolean;
  sections?: { completed: number; total: number; pending: number };
}
export interface HistoryBatch {
  items: HistoryRecord[];
  next: string | number | null;
}
export async function loadRecords(
  module: WorkspaceModule,
  query: string,
  cursor: string | number | null,
  signal: AbortSignal,
): Promise<HistoryBatch> {
  if (module === "search") {
    const page = await api.history(
      {
        query,
        cursor: typeof cursor === "string" ? cursor : null,
        pageSize: 25,
      },
      signal,
    );
    return {
      items: (page.items || []).map((item) => ({
        id: item.id,
        title: item.display_title || item.question,
        path: `/runs/${item.id}`,
        date: item.created_at,
        count: item.result_count,
        status: item.status,
        active: false,
      })),
      next: page.next_cursor || null,
    };
  }
  if (module === "bibliometrics") {
    const page = await metricsApi.list(query, Number(cursor || 0), signal);
    return {
      items: page.items.map((item) => ({
        id: item.id,
        title: item.title,
        path: `/bibliometrics/${item.id}`,
        date: item.created_at,
        count: item.paper_count,
        status: "",
        active: false,
      })),
      next: page.next_offset ?? null,
    };
  }
  const page = await reviewApi.list(Number(cursor || 0), query, signal);
  return {
    items: page.items.map((item) => ({
      id: item.id,
      title: item.display_title || item.topic,
      path: `/reviews/${item.id}`,
      date: item.updated_at,
      count: item.paper_count,
      status:
        item.phase === "needs_attention" &&
        item.section_count > 0 &&
        item.completed_sections >= item.section_count
          ? "reviewGeneratedNeedsCheck"
          : `reviewPhase_${item.phase}`,
      active: item.active,
      sections: {
        completed: item.completed_sections,
        total: item.section_count,
        pending: item.pending_sections ?? 0,
      },
    })),
    next: page.next_offset ?? null,
  };
}
export async function renameRecord(
  module: WorkspaceModule,
  id: string,
  title: string,
) {
  if (module === "search") await api.renameHistory(id, title);
  else if (module === "bibliometrics") await metricsApi.rename(id, title);
  else await reviewApi.rename(id, title);
}
export async function removeRecord(module: WorkspaceModule, id: string) {
  if (module === "search") await api.deleteHistoryRun(id);
  else if (module === "bibliometrics") await metricsApi.remove(id);
  else await reviewApi.remove(id, (await reviewApi.get(id)).version);
}
export async function exportRecord(module: WorkspaceModule, id: string) {
  if (module === "search")
    saveDownload(
      await download(`/api/v1/runs/${id}/export?format=json`, "search.json"),
    );
  else if (module === "bibliometrics")
    saveDownload(await metricsApi.export(id, "json"));
  else
    saveDownload(
      await reviewApi.export(id, (await reviewApi.get(id)).version, "bibtex"),
    );
}
