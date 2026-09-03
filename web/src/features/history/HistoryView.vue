<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";

import { api } from "../../api/client";
import type { RunDetail, RunEvent } from "../../api/types";
import { useLocale } from "../../locales";

const { language, runMessage, sourceName, t } = useLocale();
const items = ref<RunDetail[]>([]);
const nextCursor = ref<string | null>(null);
const selected = ref<RunDetail | null>(null);
const events = ref<RunEvent[]>([]);
const pageState = ref<"loading" | "error" | "loaded">("loading");
const refreshing = ref(false);
const loadingMore = ref(false);
const filterQuery = ref("");
const confirmDeleteFor = ref<RunDetail | null>(null);
const deleting = ref(false);
const deleteError = ref("");
const deleteButton = ref<HTMLButtonElement | null>(null);
const dialogCancel = ref<HTMLButtonElement | null>(null);
let generation = 0;
let controller: AbortController | null = null;

const filteredItems = computed(() => {
  const needle = filterQuery.value.trim().toLowerCase();
  if (!needle) return items.value;
  return items.value.filter((item) =>
    [item.question, item.source, sourceName(item.source), item.status, t(item.status)].filter(Boolean).join(" ").toLowerCase().includes(needle),
  );
});

function formatTime(value?: string | null): string {
  if (!value) return "";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "";
  return new Intl.DateTimeFormat(language.value === "zh" ? "zh-CN" : "en", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

async function refresh(background = false): Promise<void> {
  if (!background) pageState.value = "loading";
  refreshing.value = background;
  try {
    const page = await api.history();
    items.value = page.items;
    nextCursor.value = page.next_cursor;
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
    const page = await api.history(nextCursor.value);
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

async function askDelete(): Promise<void> {
  if (!selected.value) return;
  deleteError.value = "";
  confirmDeleteFor.value = selected.value;
  await nextTick();
  dialogCancel.value?.focus();
}

function closeDeleteDialog(): void {
  confirmDeleteFor.value = null;
  deleteButton.value?.focus();
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
  deleting.value = true;
  deleteError.value = "";
  try {
    await api.deleteHistoryRun(item.id);
    generation += 1;
    controller?.abort();
    selected.value = null;
    events.value = [];
    confirmDeleteFor.value = null;
    deleteButton.value?.focus();
    await refresh(true);
  } catch (error) {
    deleteError.value = error instanceof Error ? error.message : "loadError";
  } finally {
    deleting.value = false;
  }
}

onMounted(() => void refresh());
onBeforeUnmount(() => {
  generation += 1;
  controller?.abort();
});
</script>

<template>
  <div class="workspace-view">
    <header class="workspace-header">
      <div><h2>{{ t("history") }}</h2></div>
      <div class="alert-actions">
        <label class="field">
          <span class="sr-only">{{ t("historySearch") }}</span>
          <input v-model="filterQuery" type="search" :placeholder="t('historySearch')" :aria-label="t('historySearch')" />
        </label>
        <button class="button" type="button" :disabled="refreshing" @click="refresh(true)">{{ t("refreshHistory") }}</button>
      </div>
    </header>

    <div v-if="pageState === 'loading'" class="state-block" data-testid="history-loading">
      <span>{{ t("active") }}…</span>
    </div>
    <div v-else-if="pageState === 'error'" class="state-block state-block--error" role="alert">
      <strong>{{ t("loadError") }}</strong>
      <button class="button" type="button" @click="refresh()">{{ t("retry") }}</button>
    </div>
    <div v-else-if="!items.length" class="state-block">{{ t("noHistory") }}</div>
    <div v-else-if="!filteredItems.length" class="state-block">{{ t("noFilteredResults") }}</div>
    <section v-else class="history-layout">
      <div class="history-list">
        <div v-for="item in filteredItems" :key="item.id" class="history-item" :class="{ 'history-item--active': selected?.id === item.id }">
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
          <button class="button" type="button" :disabled="loadingMore" @click="loadMore">{{ t("loadMore") }}</button>
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
          <details class="history-technical-audit" data-testid="history-technical-audit">
            <summary data-testid="history-technical-audit-toggle">{{ t("historyTechnicalAudit") }}</summary>
            <code class="run-id">{{ selected.id }}</code>
            <section v-if="events.length">
              <h4>{{ t("events") }}</h4>
              <div class="history-event-list">
                <p v-for="event in events" :key="event.sequence"><code>{{ String(event.sequence).padStart(6, "0") }} {{ event.event_type }}</code> · {{ event.stage }} · {{ JSON.stringify(event.payload) }}</p>
              </div>
            </section>
          </details>
          <div class="history-detail-actions">
            <RouterLink class="button button--small" :to="`/runs/${selected.id}`">{{ t("workflow") }}</RouterLink>
            <RouterLink class="button button--small" :to="`/runs/${selected.id}/results`">{{ t("results") }}</RouterLink>
            <RouterLink class="button button--small" :to="`/runs/${selected.id}/citation-map`">{{ t("citationMap") }}</RouterLink>
            <a class="button button--small" :href="api.exportUrl(selected.id, 'csv')">{{ t("exportCsv") }}</a>
            <a class="button button--small" :href="api.exportUrl(selected.id, 'json')">{{ t("exportJson") }}</a>
            <button ref="deleteButton" class="button button--small button--danger" type="button" @click="askDelete">{{ t("deleteRun") }}</button>
          </div>
        </template>
        <p v-else class="field-help">{{ t("runDetail") }}</p>
      </article>
    </section>

    <div v-if="confirmDeleteFor" class="dialog-backdrop" @keydown="onDialogKeydown">
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-body">
        <h2 id="delete-dialog-title">{{ t("deleteRunTitle") }}</h2>
        <p id="delete-dialog-body">{{ t("deleteRunBody") }}</p>
        <p><strong>{{ confirmDeleteFor.question }}</strong></p>
        <p v-if="deleteError" class="field-error" role="alert">{{ t(deleteError) }}</p>
        <div class="dialog-actions">
          <button ref="dialogCancel" class="button" type="button" :disabled="deleting" @click="closeDeleteDialog">{{ t("deleteRunCancel") }}</button>
          <button class="button button--danger" type="button" :disabled="deleting" @click="confirmDelete">{{ deleting ? t("active") + "…" : t("deleteRunConfirm") }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
