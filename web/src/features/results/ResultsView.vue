<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api, type ResultPageQuery } from "../../api/client";
import type { PaperResult, RunDetail } from "../../api/types";
import { useLocale } from "../../locales";

const props = defineProps<{ snapshot?: { run: RunDetail; results: PaperResult[] } }>();
const { runMessage, sourceName, t } = useLocale();
const route = useRoute();
const runId = computed(() => String(route.params.runId || ""));
const run = ref<RunDetail | null>(null);
const results = ref<PaperResult[]>([]);
const nextCursor = ref<string | null>(null);
const pageState = ref<"loading" | "error" | "loaded">("loading");
const loadingMore = ref(false);
const loadMoreFailed = ref(false);
const refreshing = ref(false);
const refreshFailed = ref(false);
const query = ref("");
const appliedQuery = ref("");
const minScore = ref("all");
const availability = ref("all");
const sort = ref<ResultPageQuery["sort"]>("rank");
const selectedIds = ref(new Set<string>());
const uidById = new Map<string, string>();
const expanded = ref(new Set<string>());
const exporting = ref<"" | "csv" | "json">("");
const exportError = ref("");

// Server-reported summary counters (§8.1); never recomputed on the client.
const totalCount = ref<number | null>(null);
const matchedCount = ref<number | null>(null);
const scoredCount = ref<number | null>(null);
const highScoreCount = ref<number | null>(null);
const maxScore = ref<number | null>(null);

let generation = 0;
let controller: AbortController | null = null;
let queryTimer: ReturnType<typeof setTimeout> | null = null;

function paperId(paper: PaperResult): string {
  return String(paper.uid || paper.doi || paper.url || paper.title || paper.rank);
}

function rememberUids(papers: PaperResult[]): void {
  for (const paper of papers) if (paper.uid) uidById.set(paperId(paper), paper.uid);
}

function paperScore(paper: PaperResult): number | null {
  const score = paper.score ?? paper.relevance_score;
  return score === null || score === undefined ? null : Number(score);
}

function authors(paper: PaperResult): string {
  return paper.authors_text || paper.authors?.filter(Boolean).join("; ") || t("unknownAuthors");
}

function metaLine(paper: PaperResult): string {
  const parts = [
    paper.year ?? paper.publish_year ?? "",
    paper.venue || paper.source || "",
    paper.provider ? sourceName(paper.provider, paper.provider) : "",
  ].filter((value) => value !== "" && value !== null && value !== undefined);
  const citations = Number(paper.citation_count ?? paper.citations ?? 0);
  parts.push(`${citations} ${t("citations")}`);
  return parts.join(" · ");
}

const filtersActive = computed(
  () => Boolean(appliedQuery.value.trim()) || minScore.value !== "all" || availability.value !== "all" || sort.value !== "rank",
);

const summaryLine = computed(() => {
  const total = totalCount.value ?? run.value?.result_count ?? results.value.length;
  const parts = [t("resultsSummaryTotal").replace("{n}", String(total))];
  if (scoredCount.value !== null) parts.push(t("resultsSummaryScored").replace("{n}", String(scoredCount.value)));
  if (filtersActive.value && matchedCount.value !== null) {
    parts.push(t("resultsSummaryMatched").replace("{n}", String(matchedCount.value)));
  }
  if ((scoredCount.value ?? 0) > 0) {
    if (highScoreCount.value !== null) parts.push(t("resultsSummaryHighScore").replace("{n}", String(highScoreCount.value)));
    if (maxScore.value !== null) parts.push(t("resultsSummaryMax").replace("{n}", String(maxScore.value)));
  }
  return parts.join(" · ");
});

// Degraded ranking is a first-class banner; other warnings stay as a list (§8.1).
const rankingBanner = computed(() => {
  const warnings = run.value?.warnings || [];
  if (warnings.includes("ranking_failed_local_order_retained")) return t("ranking_failed_local_order_retained");
  if (warnings.includes("ranking_partial_failure_local_order_retained")) return t("ranking_partial_failure_local_order_retained");
  return "";
});
const otherWarnings = computed(() =>
  (run.value?.warnings || []).filter((warning) =>
    warning !== "ranking_failed_local_order_retained" && warning !== "ranking_partial_failure_local_order_retained"),
);

const selectedUids = computed(() =>
  [...selectedIds.value].map((id) => uidById.get(id)).filter((uid): uid is string => Boolean(uid)),
);
const outOfFilterCount = computed(() => {
  const shown = new Set(results.value.map(paperId));
  return [...selectedIds.value].filter((id) => !shown.has(id)).length;
});

function toggleSelection(paper: PaperResult): void {
  const next = new Set(selectedIds.value);
  const id = paperId(paper);
  if (next.has(id)) next.delete(id); else next.add(id);
  selectedIds.value = next;
}

function selectAllShown(): void {
  selectedIds.value = new Set([...selectedIds.value, ...results.value.map(paperId)]);
}

function isExpanded(id: string): boolean {
  return expanded.value.has(id);
}

function toggleExpanded(id: string): void {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expanded.value = next;
}

function filterParams(): ResultPageQuery {
  return {
    query: appliedQuery.value.trim() || undefined,
    minScore: minScore.value === "all" ? null : Number(minScore.value),
    metadata: availability.value === "all" ? "" : (availability.value as ResultPageQuery["metadata"]),
    sort: sort.value,
  };
}

function applySummary(page: { total_count?: number; matched_count?: number; scored_count?: number; high_score_count?: number; max_score?: number | null }): void {
  totalCount.value = page.total_count ?? null;
  matchedCount.value = page.matched_count ?? null;
  scoredCount.value = page.scored_count ?? null;
  highScoreCount.value = page.high_score_count ?? null;
  maxScore.value = page.max_score ?? null;
}

// Filter changes reset the cursor and reload page one; stale responses from an
// older filter set are fenced off by the generation counter (§8.3).
async function applyFilters(): Promise<void> {
  const value = runId.value;
  if (!value || pageState.value === "loading") return;
  const current = ++generation;
  controller?.abort();
  controller = new AbortController();
  refreshing.value = true;
  refreshFailed.value = false;
  loadMoreFailed.value = false;
  try {
    const page = await api.resultPage(value, filterParams(), controller.signal);
    if (current !== generation || runId.value !== value) return;
    results.value = page.results || [];
    rememberUids(results.value);
    nextCursor.value = page.next_cursor ?? null;
    applySummary(page);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") return;
    if (current === generation) refreshFailed.value = true;
  } finally {
    if (current === generation) refreshing.value = false;
  }
}

async function retryRefresh(): Promise<void> {
  await applyFilters();
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value || loadingMore.value) return;
  const value = runId.value;
  const current = generation;
  loadingMore.value = true;
  loadMoreFailed.value = false;
  try {
    const page = await api.resultPage(value, { ...filterParams(), cursor: nextCursor.value }, controller?.signal);
    if (current === generation && value === runId.value) {
      const known = new Set(results.value.map(paperId));
      const incoming = (page.results || []).filter((paper) => !known.has(paperId(paper)));
      rememberUids(incoming);
      results.value = [...results.value, ...incoming];
      nextCursor.value = page.next_cursor ?? null;
    }
  } catch {
    if (current === generation) loadMoreFailed.value = true;
  } finally {
    if (current === generation) loadingMore.value = false;
  }
}

async function load(value: string): Promise<void> {
  if (!value) return;
  const current = ++generation;
  controller?.abort();
  controller = new AbortController();
  run.value = null;
  results.value = [];
  nextCursor.value = null;
  selectedIds.value = new Set();
  uidById.clear();
  expanded.value = new Set();
  query.value = "";
  appliedQuery.value = "";
  minScore.value = "all";
  availability.value = "all";
  sort.value = "rank";
  exportError.value = "";
  pageState.value = "loading";
  if (props.snapshot?.run.id === value) {
    run.value = props.snapshot.run;
    results.value = props.snapshot.results;
    rememberUids(results.value);
    pageState.value = "loaded";
    return;
  }
  const [detail, page] = await Promise.allSettled([
    api.run(value, controller.signal),
    api.resultPage(value, {}, controller.signal),
  ]);
  if (current !== generation || runId.value !== value) return;
  if (detail.status === "fulfilled") run.value = detail.value;
  if (page.status === "fulfilled") {
    results.value = page.value.results || [];
    rememberUids(results.value);
    nextCursor.value = page.value.next_cursor ?? null;
    applySummary(page.value);
    pageState.value = "loaded";
  } else {
    pageState.value = "error";
  }
}

watch(runId, (value) => void load(value), { immediate: true });

// Keyword search is debounced (180ms); discrete filters apply immediately (§8.3).
watch(query, (value) => {
  if (queryTimer) clearTimeout(queryTimer);
  queryTimer = setTimeout(() => {
    appliedQuery.value = value;
    void applyFilters();
  }, 180);
});
watch([minScore, availability, sort], () => void applyFilters());

async function exportSelected(format: "csv" | "json"): Promise<void> {
  const uids = selectedUids.value;
  if (!uids.length || exporting.value) return;
  exporting.value = format;
  exportError.value = "";
  try {
    const file = await api.exportSelected(runId.value, format, uids);
    const url = URL.createObjectURL(file.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = file.filename;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    exportError.value = error instanceof Error ? error.message : "export_failed";
  } finally {
    exporting.value = "";
  }
}

function clearFilters(): void {
  query.value = "";
  appliedQuery.value = "";
  minScore.value = "all";
  availability.value = "all";
  sort.value = "rank";
  void applyFilters();
}

onBeforeUnmount(() => {
  generation += 1;
  controller?.abort();
  if (queryTimer) clearTimeout(queryTimer);
});
</script>

<template>
  <div class="workspace-view">
    <header class="workspace-header">
      <div>
        <div class="section-kicker">{{ t("results") }}</div>
        <h2>{{ run?.question || t("noRun") }}</h2>
        <RouterLink v-if="run" class="back-link" :to="`/runs/${runId}`">{{ t("backToRun") }}</RouterLink>
      </div>
      <div v-if="run" class="alert-actions">
        <slot name="exports" :run-id="runId" :selected-uids="selectedUids">
          <a class="button button--primary" :href="api.exportUrl(runId, 'csv')">{{ t("exportAllCsv") }}</a>
          <a class="button" :href="api.exportUrl(runId, 'json')">{{ t("exportAllJson") }}</a>
          <button class="button" type="button" data-testid="export-selected-csv" :disabled="!selectedUids.length || Boolean(exporting)" @click="exportSelected('csv')">
            {{ exporting === "csv" ? t("active") + "…" : t("exportSelectedCsv") + (selectedUids.length ? ` (${selectedUids.length})` : "") }}
          </button>
          <button class="button" type="button" data-testid="export-selected-json" :disabled="!selectedUids.length || Boolean(exporting)" @click="exportSelected('json')">
            {{ exporting === "json" ? t("active") + "…" : t("exportSelectedJson") + (selectedUids.length ? ` (${selectedUids.length})` : "") }}
          </button>
        </slot>
      </div>
    </header>

    <div v-if="pageState === 'loading'" class="state-block" data-testid="results-loading">
      <span>{{ t("active") }}…</span>
    </div>
    <div v-else-if="pageState === 'error'" class="state-block state-block--error" role="alert">
      <strong>{{ t("loadError") }}</strong>
      <button class="button" type="button" @click="load(runId)">{{ t("retry") }}</button>
    </div>
    <template v-else>
      <p v-if="rankingBanner" class="alert alert--warning" data-testid="ranking-banner" role="status">{{ rankingBanner }}</p>
      <ul v-if="otherWarnings.length" class="run-warnings" data-testid="results-warnings">
        <li v-for="warning in otherWarnings" :key="warning">{{ runMessage(warning) }}</li>
      </ul>
      <p v-if="exportError" class="alert" role="alert">{{ t(exportError) === exportError ? t("exportFailed") : t(exportError) }}</p>

      <section class="results-summary" :aria-label="t('resultsSummary')" data-testid="results-summary">
        <span>{{ summaryLine }}</span>
        <span v-if="refreshing" class="field-help" role="status">{{ t("refreshing") }}</span>
      </section>

      <div v-if="refreshFailed" class="alert" role="alert">
        <strong>{{ t("loadError") }}</strong>
        <div class="alert-actions">
          <button class="button button--small" type="button" @click="retryRefresh">{{ t("retry") }}</button>
        </div>
      </div>

      <section class="workspace-toolbar" :aria-label="t('resultControls')">
        <label class="field"><span class="field-label">{{ t("searchResults") }}</span><input v-model="query" type="search"></label>
        <label class="field"><span class="field-label">{{ t("minimumScore") }}</span>
          <select v-model="minScore">
            <option value="all">{{ t("allScores") }}</option>
            <option v-for="value in ['7', '8', '9']" :key="value" :value="value">{{ t("atLeastScore").replace("{n}", value) }}</option>
          </select>
        </label>
        <label class="field"><span class="field-label">{{ t("availability") }}</span>
          <select v-model="availability"><option value="all">{{ t("allMetadata") }}</option><option value="abstract">{{ t("hasAbstract") }}</option><option value="doi">{{ t("hasDoi") }}</option><option value="pdf">{{ t("hasPdf") }}</option></select>
        </label>
        <label class="field"><span class="field-label">{{ t("sortResults") }}</span>
          <select v-model="sort"><option value="rank">{{ t("sortRank") }}</option><option value="score">{{ t("sortScore") }}</option><option value="citations">{{ t("sortCitations") }}</option><option value="year">{{ t("sortYear") }}</option></select>
        </label>
        <button class="button" type="button" @click="selectAllShown">{{ t("selectAllShown") }}</button>
        <button class="button" type="button" @click="selectedIds = new Set()">{{ t("clearSelection") }}</button>
        <span class="toolbar-counts">
          <span data-testid="selection-count">{{ selectedIds.size }} {{ t("selected") }}</span>
          <span v-if="outOfFilterCount" class="field-help" data-testid="selection-out-of-filter">{{ t("selectionOutOfFilter").replace("{n}", String(outOfFilterCount)) }}</span>
        </span>
      </section>

      <div v-if="!results.length && !filtersActive" class="state-block">{{ t("noResults") }}</div>
      <div v-else-if="!results.length" class="state-block" data-testid="no-filtered-results">
        <span>{{ t("noFilteredResults") }}</span>
        <button class="button button--small" type="button" @click="clearFilters">{{ t("clearFilters") }}</button>
      </div>
      <section class="results-list">
        <article v-for="paper in results" :key="paperId(paper)" class="result-card" :class="{ 'result-card--selected': selectedIds.has(paperId(paper)) }" data-testid="result-card">
          <div class="result-score" data-testid="result-score" :class="{ 'result-score--none': paperScore(paper) === null }">
            <template v-if="paperScore(paper) !== null">{{ paperScore(paper) }}<span class="result-score-scale">/10</span></template>
            <span v-else>{{ t("notScored") }}</span>
          </div>
          <div class="result-copy">
            <div class="result-title-row">
              <input type="checkbox" :checked="selectedIds.has(paperId(paper))" :aria-label="`${t('selected')}: ${paper.title}`" @change="toggleSelection(paper)">
              <h3 class="result-title">
                <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener">{{ paper.title }}</a>
                <template v-else>{{ paper.title }}</template>
              </h3>
              <span class="result-rank">{{ t("rankLabel") }} {{ paper.rank }}</span>
            </div>
            <div class="result-clamp-block">
              <p class="result-meta" :class="{ 'result-clamp result-clamp--2': !isExpanded(`${paperId(paper)}:authors`) }">{{ authors(paper) }}</p>
              <button v-if="authors(paper).length > 120" class="clamp-toggle" type="button" @click="toggleExpanded(`${paperId(paper)}:authors`)">
                {{ isExpanded(`${paperId(paper)}:authors`) ? t("collapse") : t("expandAll") }}
              </button>
            </div>
            <p class="result-meta">{{ metaLine(paper) }}</p>
            <div class="result-clamp-block">
              <template v-if="paper.abstract">
                <p class="result-abstract" :class="{ 'result-clamp result-clamp--3': !isExpanded(`${paperId(paper)}:abstract`) }"><span class="detail-label">{{ t("abstract") }}</span> {{ paper.abstract }}</p>
                <button v-if="paper.abstract.length > 240" class="clamp-toggle" type="button" @click="toggleExpanded(`${paperId(paper)}:abstract`)">
                  {{ isExpanded(`${paperId(paper)}:abstract`) ? t("collapse") : t("expandAll") }}
                </button>
              </template>
              <p v-else-if="paper.metadata_status === 'degraded'" class="result-meta">{{ t("abstractFailed") }}</p>
              <p v-else class="result-meta">{{ t("noAbstract") }}</p>
            </div>
            <div v-if="paper.reasoning || paper.relevance_reason" class="result-clamp-block">
              <p class="result-reasoning" :class="{ 'result-clamp result-clamp--2': !isExpanded(`${paperId(paper)}:reasoning`) }"><span class="detail-label">{{ t("reasoning") }}</span> {{ paper.reasoning || paper.relevance_reason }}</p>
              <button v-if="(paper.reasoning || paper.relevance_reason || '').length > 160" class="clamp-toggle" type="button" @click="toggleExpanded(`${paperId(paper)}:reasoning`)">
                {{ isExpanded(`${paperId(paper)}:reasoning`) ? t("collapse") : t("expandAll") }}
              </button>
            </div>
            <div class="result-links">
              <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener">{{ t("record") }}</a>
              <a v-if="paper.pdf_url" :href="paper.pdf_url" target="_blank" rel="noopener">PDF</a>
              <details class="result-details">
                <summary role="button">
                  <svg class="disclosure-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
                  {{ t("bibliographicDetails") }}
                </summary>
                <div class="result-details-body">
                  <p v-if="paper.doi"><span class="detail-label">DOI</span> <code>{{ paper.doi }}</code> <a :href="`https://doi.org/${paper.doi}`" target="_blank" rel="noopener">doi.org</a></p>
                  <p v-if="paper.keywords"><span class="detail-label">{{ t("keywords") }}</span> {{ Array.isArray(paper.keywords) ? paper.keywords.join('; ') : paper.keywords }}</p>
                  <p v-if="paper.document_types?.length || paper.publication_type"><span class="detail-label">{{ t("publicationType") }}</span> {{ (paper.document_types?.length ? paper.document_types.join('; ') : paper.publication_type) }}</p>
                  <p v-if="paper.venue || paper.source"><span class="detail-label">{{ t("venue") }}</span> {{ paper.venue || paper.source }}</p>
                  <p v-if="paper.provider"><span class="detail-label">{{ t("dataSource") }}</span> {{ sourceName(paper.provider, paper.provider) }}</p>
                </div>
              </details>
            </div>
          </div>
        </article>
      </section>
      <div v-if="nextCursor" class="load-more-row">
        <button class="button" type="button" :disabled="loadingMore" @click="loadMore">{{ t("loadMore") }}</button>
      </div>
      <div v-if="loadMoreFailed" class="load-more-row">
        <span class="field-help" role="alert">{{ t("loadError") }}</span>
        <button class="button button--small" type="button" @click="loadMore">{{ t("retry") }}</button>
      </div>
    </template>
  </div>
</template>
