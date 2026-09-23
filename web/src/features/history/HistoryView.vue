<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { api } from "../../api/client";
import type { RunDetail, RunEvent } from "../../api/types";
import { useLocale } from "../../locales";
import SystemLogPanel from "../search/SystemLogPanel.vue";

const { language, runMessage, sourceName, t } = useLocale();
const items = ref<RunDetail[]>([]);
const nextCursor = ref<string | null>(null);
const selected = ref<RunDetail | null>(null);
const events = ref<RunEvent[]>([]);
const pageState = ref<"loading" | "error" | "loaded">("loading");
const refreshing = ref(false);
const loadingMore = ref(false);
const searchInput = ref("");
const searchQuery = ref("");
const matchedCount = ref<number | null>(null);
const confirmDeleteFor = ref<RunDetail | "all" | null>(null);
const deleting = ref(false);
const deleteError = ref("");
const deleteButton = ref<HTMLButtonElement | null>(null);
const clearButton = ref<HTMLButtonElement | null>(null);
const refreshButton = ref<HTMLButtonElement | null>(null);
const dialogCancel = ref<HTMLButtonElement | null>(null);
let generation = 0;
let controller: AbortController | null = null;
let deleteController: AbortController | null = null;
let searchTimer: ReturnType<typeof setTimeout> | null = null;
const terminalStatuses = new Set(["completed", "completed_with_warnings", "failed", "cancelled"]);
const canClear = computed(() => nextCursor.value || items.value.some(item => terminalStatuses.has(item.status)));

function formatTime(value?: string | null): string {
  if (!value) return "";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "";
  return new Intl.DateTimeFormat(language.value === "zh" ? "zh-CN" : "en", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

// History search is server-side: the query reloads the list from page one and
// the cursor stays bound to that query (§9.2).
watch(searchInput, (value) => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    searchQuery.value = value.trim();
    void refresh();
  }, 180);
});

async function refresh(background = false): Promise<void> {
  if (!background) pageState.value = "loading";
  refreshing.value = background;
  try {
    const page = await api.history({ query: searchQuery.value || undefined });
    items.value = page.items;
    nextCursor.value = page.next_cursor;
    matchedCount.value = page.matched_count;
    pageState.value = "loaded";
    if (selected.value && !page.items.some((item) => item.id === selected.value?.id)) {
      selected.value = null;
      events.value = [];
    }
  } catch {
    if (!items.value.length) pageState.value = "error";
  } finally {
    refreshing.value = false;
  }
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await api.history({ cursor: nextCursor.value, query: searchQuery.value || undefined });
    const known = new Set(items.value.map((item) => item.id));
    items.value = [...items.value, ...page.items.filter((item) => !known.has(item.id))];
    nextCursor.value = page.next_cursor;
  } finally {
    loadingMore.value = false;
  }
}

async function choose(item: RunDetail): Promise<void> {
  const current = ++generation;
  controller?.abort();
  controller = new AbortController();
  selected.value = await api.run(item.id, controller.signal).catch(() => item);
  events.value = [];
  await api.events(item.id, 0, (event) => {
    if (current === generation && selected.value?.id === item.id && !events.value.some((known) => known.sequence === event.sequence)) {
      events.value = [...events.value, event].sort((left, right) => left.sequence - right.sequence);
    }
  }, controller.signal).catch(() => undefined);
}

async function askDelete(all = false): Promise<void> {
  if (deleting.value || (!all && !selected.value)) return;
  deleteError.value = "";
  confirmDeleteFor.value = all ? "all" : selected.value;
  await nextTick();
  dialogCancel.value?.focus();
}

function closeDeleteDialog(): void {
  if (deleting.value) return;
  const trigger = confirmDeleteFor.value === "all" ? clearButton.value : deleteButton.value;
  confirmDeleteFor.value = null;
  trigger?.focus();
}

function onDialogKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    closeDeleteDialog();
    return;
  }
  if (event.key !== "Tab") return;
  const dialog = (event.currentTarget as HTMLElement).querySelector(".dialog");
  const focusable = Array.from(dialog?.querySelectorAll<HTMLElement>("button, [href]") || []).filter(
    (element) => !element.hasAttribute("disabled"),
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

async function confirmDelete(): Promise<void> {
  const item = confirmDeleteFor.value;
  if (!item || deleting.value) return;
  const request = new AbortController();
  deleteController = request;
  deleting.value = true;
  deleteError.value = "";
  try {
    const ids = new Set<string>();
    if (item === "all") {
      // Collect before deleting: a failed page read must not clear only the visible page.
      // Clear always walks the full unfiltered history, regardless of the search box (§9.3).
      let cursor: string | undefined;
      do {
        const page = await api.history({ cursor }, request.signal);
        request.signal.throwIfAborted();
        for (const run of page.items) if (terminalStatuses.has(run.status)) ids.add(run.id);
        cursor = page.next_cursor || undefined;
      } while (cursor);
    } else ids.add(item.id);
    for (const id of ids) {
      request.signal.throwIfAborted();
      await api.deleteHistoryRun(id, request.signal);
      request.signal.throwIfAborted();
      items.value = items.value.filter(run => run.id !== id);
      if (selected.value?.id === id) {
        generation += 1;
        controller?.abort();
        selected.value = null;
        events.value = [];
      }
    }
    confirmDeleteFor.value = null;
    await refresh(true);
  } catch (error) {
    if (!request.signal.aborted) deleteError.value = item === "all" ? "clearHistoryFailed"
      : error instanceof Error ? error.message : "loadError";
  } finally {
    deleting.value = false;
    deleteController = null;
    if (!confirmDeleteFor.value && !request.signal.aborted) {
      await nextTick();
      refreshButton.value?.focus();
    }
  }
}

onMounted(() => void refresh());
onBeforeUnmount(() => {
  generation += 1;
  controller?.abort();
  deleteController?.abort();
  if (searchTimer) clearTimeout(searchTimer);
});
</script>

<template>
  <div class="workspace-view">
    <header class="workspace-header">
      <div><h2>{{ t("history") }}</h2></div>
      <div class="workspace-toolbar history-toolbar">
        <label class="field">
          <span class="sr-only">{{ t("historySearch") }}</span>
          <input v-model="searchInput" type="search" :placeholder="t('historySearch')" :aria-label="t('historySearch')" />
        </label>
        <button ref="refreshButton" class="button" type="button" :disabled="refreshing || deleting" @click="refresh(true)">{{ t("refreshHistory") }}</button>
        <button ref="clearButton" class="button button--danger" type="button" :disabled="pageState !== 'loaded' || !canClear || refreshing || loadingMore || deleting" @click="askDelete(true)">{{ t("clearHistory") }}</button>
      </div>
    </header>
    <p v-if="searchQuery && matchedCount !== null" class="field-help" data-testid="history-matched">{{ t("historyMatched").replace("{n}", String(matchedCount)) }}</p>

    <div v-if="pageState === 'loading'" class="state-block" data-testid="history-loading">
      <span>{{ t("active") }}…</span>
    </div>
    <div v-else-if="pageState === 'error'" class="state-block state-block--error" role="alert">
      <strong>{{ t("loadError") }}</strong>
      <button class="button" type="button" @click="refresh()">{{ t("retry") }}</button>
    </div>
    <div v-else-if="!items.length && searchQuery" class="state-block">{{ t("noFilteredResults") }}</div>
    <div v-else-if="!items.length" class="state-block">{{ t("noHistory") }}</div>
    <section v-else class="history-layout">
      <div class="history-list">
        <div v-for="item in items" :key="item.id" class="history-item" :class="{ 'history-item--active': selected?.id === item.id }">
          <button class="history-open" type="button" @click="choose(item)">
            <strong>{{ item.question }}</strong>
            <span class="history-item-meta">
              <span>{{ sourceName(item.source) }}</span>
              <span class="badge" :class="item.status === 'failed' || item.status === 'cancelled' ? 'badge--danger' : item.status === 'completed' || item.status === 'completed_with_warnings' ? 'badge--success' : 'badge--accent'">{{ t(item.status) }}</span>
              <span>{{ formatTime(item.created_at) }}</span>
              <span v-if="item.warnings?.length">{{ item.warnings.length }} {{ t("warnings") }}</span>
            </span>
          </button>
          <div class="history-item-actions">
            <RouterLink :data-testid="`history-flow-${item.id}`" :to="`/runs/${item.id}`">{{ t("workflow") }}</RouterLink>
            <RouterLink :data-testid="`history-results-${item.id}`" :to="`/runs/${item.id}/results`">{{ t("results") }}</RouterLink>
            <RouterLink :data-testid="`history-citation-map-${item.id}`" :to="`/runs/${item.id}/citation-map`">{{ t("citationMap") }}</RouterLink>
          </div>
        </div>
        <div v-if="nextCursor" class="load-more-row">
          <button class="button" type="button" :disabled="loadingMore || deleting" @click="loadMore">{{ t("loadMore") }}</button>
        </div>
      </div>
      <article class="history-detail" data-testid="history-detail">
        <template v-if="selected">
          <div data-testid="history-primary-detail">
            <div class="section-kicker">{{ t("runDetail") }}</div>
            <h3>{{ selected.question }}</h3>
            <div class="history-item-meta">
              <span>{{ sourceName(selected.source) }}</span>
              <span>{{ t(selected.status) }}</span>
              <span>{{ selected.result_count || 0 }} {{ t("results") }}</span>
              <span>{{ t("createdAt") }}: {{ formatTime(selected.created_at) }}</span>
            </div>
            <p v-if="selected.warnings?.length"><strong>{{ t("warnings") }}:</strong> {{ selected.warnings.map((warning) => runMessage(warning)).join(" · ") }}</p>
            <p v-if="selected.error_code"><strong>{{ t("error") }}:</strong> {{ runMessage(selected.error_code, "error") }}</p>
          </div>
          <SystemLogPanel
            id-prefix="history-system-log"
            :run-id="selected.id"
            :events="events"
            :terminal="terminalStatuses.has(selected.status)"
          />
          <div class="history-detail-actions">
            <RouterLink class="button button--small" :to="`/runs/${selected.id}`">{{ t("workflow") }}</RouterLink>
            <RouterLink class="button button--small" :to="`/runs/${selected.id}/results`">{{ t("results") }}</RouterLink>
            <RouterLink class="button button--small" :to="`/runs/${selected.id}/citation-map`">{{ t("citationMap") }}</RouterLink>
            <slot name="exports" :run-id="selected.id">
              <a class="button button--small" :href="api.exportUrl(selected.id, 'csv')">{{ t("exportCsv") }}</a>
              <a class="button button--small" :href="api.exportUrl(selected.id, 'json')">{{ t("exportJson") }}</a>
            </slot>
            <button ref="deleteButton" class="button button--small button--danger" type="button" :disabled="deleting" @click="askDelete()">{{ t("deleteRun") }}</button>
          </div>
        </template>
        <p v-else class="field-help">{{ t("runDetail") }}</p>
      </article>
    </section>

    <div v-if="confirmDeleteFor" class="dialog-backdrop" @keydown="onDialogKeydown">
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-body">
        <h2 id="delete-dialog-title">{{ t(confirmDeleteFor === 'all' ? "clearHistoryTitle" : "deleteRunTitle") }}</h2>
        <p id="delete-dialog-body">{{ t(confirmDeleteFor === 'all' ? "clearHistoryBody" : "deleteRunBody") }}</p>
        <p v-if="confirmDeleteFor !== 'all'"><strong>{{ confirmDeleteFor.question }}</strong></p>
        <p v-if="deleteError" class="field-error" role="alert">{{ t(deleteError) }}</p>
        <div class="dialog-actions">
          <button ref="dialogCancel" class="button" type="button" :disabled="deleting" @click="closeDeleteDialog">{{ t("deleteRunCancel") }}</button>
          <button class="button button--danger" type="button" :disabled="deleting" @click="confirmDelete">{{ deleting ? t("active") + "…" : t("deleteRunConfirm") }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
