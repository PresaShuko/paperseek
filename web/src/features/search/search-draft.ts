import { reactive } from "vue";
import type { SearchSubmission } from "../../api/types";
import type { Defaults } from "../settings/store";

export type PreRankingMode = "local_fusion" | "embedding_rerank" | "decision";
export type SearchBudget = NonNullable<SearchSubmission["search_budget"]> | "auto";

// One in-memory draft survives module navigation. It names saved connections;
// keys never reach the browser.
const initialSearchDraft = {
  question: "",
  source: "",
  searchBudget: "auto" as SearchBudget,
  fieldIds: [] as string[],
  fieldHint: "",
  citationEnabled: true,
  llmConnection: "",
  preRankingMode: "local_fusion" as PreRankingMode,
  // Set once the saved defaults have been applied to this draft.
  defaultsApplied: false,
};
export const searchDraft = reactive(structuredClone(initialSearchDraft));
export type SearchDraft = typeof searchDraft;

export function resetSearchDraft() {
  Object.assign(searchDraft, structuredClone(initialSearchDraft));
}

/** Fill the draft's options from Settings defaults; the question is kept. */
export function applyDefaults(defaults: Defaults, force = false) {
  if (searchDraft.defaultsApplied && !force) return;
  searchDraft.source = defaults.source;
  searchDraft.searchBudget = "auto";
  searchDraft.fieldIds = [];
  searchDraft.fieldHint = "";
  searchDraft.citationEnabled = true;
  searchDraft.llmConnection = defaults.search_llm;
  searchDraft.preRankingMode = defaults.pre_ranking;
  searchDraft.defaultsApplied = true;
}
