<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api } from "../../api/client";
import type { PaperResult, RunDetail } from "../../api/types";
import { useLocale } from "../../locales";

const { sourceName, t } = useLocale();
const route = useRoute();
const runId = computed(() => String(route.params.runId || ""));
const run = ref<RunDetail | null>(null);
const results = ref<PaperResult[]>([]);
const nextCursor = ref<string | null>(null);
const pageState = ref<"loading" | "error" | "loaded">("loading");
const loadingMore = ref(false);
const query = ref("");
const minScore = ref("all");
const availability = ref("all");
const sort = ref("rank");
const selectedIds = ref(new Set<string>());
let generation = 0;
let controller: AbortController | null = null;

function paperId(paper: PaperResult): string {
  return String(paper.uid || paper.doi || paper.url || paper.title || paper.rank);
}

function paperScore(paper: PaperResult): number {
  return Number(paper.score ?? paper.relevance_score ?? 0);
}

function authors(paper: PaperResult): string {
  return paper.authors_text || paper.authors?.filter(Boolean).join("; ") || t("unknownAuthors");
}

function meta(paper: PaperResult): string {
  return [paper.year || paper.publish_year, paper.venue || paper.source, paper.provider ? sourceName(paper.provider, paper.provider) : ""]
    .filter((value) => value !== undefined && value !== null && value !== "")
    .join(" · ");
}

function citations(paper: PaperResult): number {
  return Number(paper.citation_count ?? paper.citations ?? 0);
}

const filteredResults = computed(() => {
  const needle = query.value.trim().toLowerCase();
  const papers = results.value.filter((paper) => {
    if (needle) {
      const haystack = [paper.title, authors(paper), paper.abstract, paper.doi, paper.venue, paper.source, paper.keywords]
        .flat().filter(Boolean).join(" ").toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    if (minScore.value !== "all" && paperScore(paper) < Number(minScore.value)) return false;
    if (availability.value === "abstract" && !paper.abstract) return false;
    if (availability.value === "doi" && !paper.doi) return false;
    if (availability.value === "pdf" && !paper.pdf_url) return false;
    return true;
  });
  return papers.sort((left, right) => {
    if (sort.value === "score") return paperScore(right) - paperScore(left);
    if (sort.value === "citations") return citations(right) - citations(left);
    if (sort.value === "year") return Number(right.year ?? right.publish_year ?? 0) - Number(left.year ?? left.publish_year ?? 0);
    return left.rank - right.rank;
  });
});

const highScoreCount = computed(() => results.value.filter((paper) => paperScore(paper) >= 5).length);
const maxScore = computed(() => results.value.reduce((max, paper) => Math.max(max, paperScore(paper)), 0));

function toggleSelection(paper: PaperResult): void {
  const next = new Set(selectedIds.value);
  const id = paperId(paper);
  if (next.has(id)) next.delete(id); else next.add(id);
  selectedIds.value = next;
}

function selectAllShown(): void {
  selectedIds.value = new Set([...selectedIds.value, ...filteredResults.value.map(paperId)]);
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value || loadingMore.value) return;
  const value = runId.value;
  const current = generation;
  loadingMore.value = true;
  try {
    const page = await api.resultPage(value, nextCursor.value, controller?.signal);
    if (current === generation && value === runId.value) {
      const known = new Set(results.value.map(paperId));
      results.value = [...results.value, ...(page.results || []).filter((paper) => !known.has(paperId(paper)))];
      nextCursor.value = page.next_cursor ?? null;
    }
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
  query.value = "";
  minScore.value = "all";
  availability.value = "all";
  sort.value = "rank";
  pageState.value = "loading";
  const [detail, page] = await Promise.allSettled([
    api.run(value, controller.signal),
    api.resultPage(value, undefined, controller.signal),
  ]);
  if (current !== generation || runId.value !== value) return;
  if (detail.status === "fulfilled") run.value = detail.value;
  if (page.status === "fulfilled") {
    results.value = page.value.results || [];
    nextCursor.value = page.value.next_cursor ?? null;
    pageState.value = "loaded";
  } else {
    pageState.value = "error";
  }
}

watch(runId, (value) => void load(value), { immediate: true });

onBeforeUnmount(() => {
  generation += 1;
  controller?.abort();
});
</script>

<template>
  <div class="workspace-view">
    <header class="workspace-header">
      <div><div class="section-kicker">{{ t("results") }}</div><h2>{{ run?.question || t("noRun") }}</h2></div>
      <div v-if="run" class="alert-actions">
        <a class="button button--primary" :href="api.exportUrl(runId, 'csv')">{{ t("exportCsv") }}</a>
        <a class="button" :href="api.exportUrl(runId, 'json')">{{ t("exportJson") }}</a>
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
      <section v-if="results.length" class="results-summary" :aria-label="t('resultsSummary')">
        <div class="summary-item"><span class="summary-value">{{ run?.result_count ?? results.length }}</span><span class="summary-label">{{ t("resultCount") }}</span></div>
        <div class="summary-item"><span class="summary-value">{{ highScoreCount }}</span><span class="summary-label">{{ t("highScoreCount") }}</span></div>
        <div class="summary-item"><span class="summary-value">{{ maxScore || "—" }}</span><span class="summary-label">{{ t("maxScore") }}</span></div>
      </section>

      <section v-if="results.length" class="results-toolbar" :aria-label="t('resultControls')">
        <label class="field"><span class="field-label">{{ t("searchResults") }}</span><input v-model="query" type="search"></label>
        <label class="field"><span class="field-label">{{ t("minimumScore") }}</span>
          <select v-model="minScore"><option value="all">{{ t("allScores") }}</option><option value="8">8</option><option value="9">9</option></select>
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
          <span>{{ filteredResults.length }} {{ t("shown") }}</span>
          <span data-testid="selection-count">{{ selectedIds.size }} {{ t("selected") }}</span>
        </span>
      </section>

      <div v-if="!results.length" class="state-block">{{ t("noResults") }}</div>
      <div v-else-if="!filteredResults.length" class="state-block">{{ t("noFilteredResults") }}</div>
      <section class="results-list">
        <article v-for="paper in filteredResults" :key="paperId(paper)" class="result-card" data-testid="result-card">
          <div class="result-rank">#{{ paper.rank }}</div>
          <div class="result-copy">
            <div class="result-title-row">
              <input type="checkbox" :checked="selectedIds.has(paperId(paper))" :aria-label="`${t('selectAllShown')}: ${paper.title}`" @change="toggleSelection(paper)">
              <h3 class="result-title">{{ paper.title }}</h3>
            </div>
            <span class="badge" data-testid="metadata-status">{{ t(paper.metadata_status || "not_requested") }}</span>
            <p class="result-meta">{{ authors(paper) }}<template v-if="meta(paper)"> · {{ meta(paper) }}</template></p>
            <details class="result-details">
              <summary role="button">
                <svg class="disclosure-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
                {{ t("showDetails") }}
              </summary>
              <div class="result-details-body">
                <p v-if="paper.doi"><span class="detail-label">DOI</span> {{ paper.doi }}</p>
                <p v-if="paper.keywords"><span class="detail-label">{{ t("keywords") }}</span> {{ Array.isArray(paper.keywords) ? paper.keywords.join('; ') : paper.keywords }}</p>
                <p v-if="paper.abstract"><span class="detail-label">{{ t("abstract") }}</span> {{ paper.abstract }}</p>
                <p v-if="paper.reasoning || paper.relevance_reason"><span class="detail-label">{{ t("reasoning") }}</span> {{ paper.reasoning || paper.relevance_reason }}</p>
                <div class="result-links">
                  <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener">{{ t("record") }}</a>
                  <a v-if="paper.pdf_url" :href="paper.pdf_url" target="_blank" rel="noopener">PDF</a>
                </div>
              </div>
            </details>
            <span class="result-meta">{{ citations(paper) }} {{ t("citations") }}</span>
          </div>
          <strong class="result-score" :class="{ 'result-score--none': paper.score === undefined && paper.relevance_score === undefined }">{{ paper.score ?? paper.relevance_score ?? "—" }}</strong>
        </article>
      </section>
      <div v-if="nextCursor" class="load-more-row">
        <button class="button" type="button" :disabled="loadingMore" @click="loadMore">{{ t("loadMore") }}</button>
      </div>
    </template>
  </div>
</template>
