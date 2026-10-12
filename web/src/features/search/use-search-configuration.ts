import type { Ref } from "vue";
import type { RunDetail, SearchSubmission, SourceDescriptor } from "../../api/types";
import { workspaceSettings } from "../settings/store";
import { applyDefaults, searchDraft, type PreRankingMode } from "./search-draft";

/** The submission built from the draft: saved connections are resolved by the server. */
export function useSearchConfiguration(sources: Ref<SourceDescriptor[]>) {
  const form = searchDraft;

  function configurationPayload(): Omit<SearchSubmission, "question"> {
    const source = sources.value.find((item) => item.id === form.source);
    const filter = source?.capabilities.filter;
    const defaults = workspaceSettings.defaults;
    const mode = form.preRankingMode;
    return {
      source: form.source,
      search_budget: form.searchBudget === "auto" ? "fast" : form.searchBudget,
      field_ids: filter?.mode === "native" ? form.fieldIds : [],
      field_hint: filter?.mode === "text" ? form.fieldHint : "",
      citation_enabled: Boolean(source?.capabilities.citation_expansion) && form.citationEnabled,
      retrieval: { mode },
      connections: {
        llm: form.llmConnection,
        embedding: mode === "embedding_rerank" ? defaults?.embedding || "" : "",
        reranker: mode === "embedding_rerank" ? defaults?.reranker || "" : "",
        decision: mode === "decision" ? defaults?.decision || "" : "",
      },
    };
  }

  // "Edit and run again" copies the public configuration; the model stays the saved choice.
  function restoreRun(run: RunDetail | null): void {
    // Apply defaults first so the create page does not overwrite the restored values.
    if (!form.defaultsApplied && workspaceSettings.defaults) applyDefaults(workspaceSettings.defaults);
    const snap = run?.config_snapshot || {};
    if (run?.question) form.question = run.question;
    if (run?.source && sources.value.some((source) => source.id === run.source)) form.source = run.source;
    if (typeof snap.search_budget === "string" && ["fast", "medium", "high", "max"].includes(snap.search_budget))
      form.searchBudget = snap.search_budget as typeof form.searchBudget;
    if (Array.isArray(snap.field_ids)) form.fieldIds = snap.field_ids.map(String);
    if (typeof snap.field_hint === "string") form.fieldHint = snap.field_hint;
    if (typeof snap.citation_enabled === "boolean") form.citationEnabled = snap.citation_enabled;
    const mode = snap.retrieval?.mode;
    if (mode && ["local_fusion", "embedding_rerank", "decision"].includes(mode)) form.preRankingMode = mode as PreRankingMode;
  }

  return { form, configurationPayload, restoreRun };
}
