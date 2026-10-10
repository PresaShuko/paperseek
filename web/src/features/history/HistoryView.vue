<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, watchEffect } from "vue";
import { api } from "../../api/client";
import type { HistoryItem } from "../../api/types";
import AppDialog from "../../components/AppDialog.vue";
import Icon from "../../components/Icon.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import { toast } from "../../components/toast";
import { useLocale } from "../../locales";
import { useUi } from "../../locales/ui";
import { useDates } from "../workspace/format";
import RecordMenu from "../workspace/RecordMenu.vue";
import { historyRevision, invalidateHistory, setHeader } from "../workspace/state";

const { sourceName } = useLocale();
const u = useUi();
const { short } = useDates();
const items = ref<HistoryItem[]>([]);
const nextCursor = ref<string | null>(null);
const pageState = ref<"loading" | "error" | "loaded">("loading");
const refreshing = ref(false);
const loadingMore = ref(false);
const listError = ref(false);
const searchInput = ref("");
const searchQuery = ref("");
const matchedCount = ref<number | null>(null);
const confirmClear = ref(false);
const clearing = ref(false);
const clearError = ref(false);
let listController: AbortController | null = null;
let generation = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
const terminal = new Set(["completed", "completed_with_warnings", "failed", "cancelled"]);
const canClear = computed(() => Boolean(nextCursor.value) || items.value.some((item) => terminal.has(item.status)));
const countText = computed(() => {
  const matched = searchQuery.value ? matchedCount.value : null;
  const count = matched ?? items.value.length;
  return u("totalItems", { n: `${count.toLocaleString()}${nextCursor.value && matched === null ? "+" : ""}` });
});

watchEffect(() => setHeader(u("search")));

watch(searchInput, (value) => {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    searchQuery.value = value.trim();
    void refresh();
  }, 180);
});
watch(() => historyRevision.search, () => void refresh(true));

async function refresh(background = false) {
  const current = ++generation;
  listController?.abort();
  const request = new AbortController();
  listController = request;
  if (!items.value.length) pageState.value = "loading";
  refreshing.value = background;
  listError.value = false;
  try {
    const page = await api.history({ query: searchQuery.value || undefined }, request.signal);
    if (current !== generation) return;
    items.value = page.items || [];
    nextCursor.value = page.next_cursor ?? null;
    matchedCount.value = page.matched_count ?? null;
    pageState.value = "loaded";
  } catch {
    if (request.signal.aborted || current !== generation) return;
    pageState.value = items.value.length ? "loaded" : "error";
    listError.value = true;
  } finally {
    if (current === generation) refreshing.value = false;
  }
}
async function loadMore() {
  if (!nextCursor.value || loadingMore.value) return;
  const current = generation;
  loadingMore.value = true;
  try {
    const page = await api.history({ cursor: nextCursor.value, query: searchQuery.value || undefined }, listController?.signal);
    if (current !== generation) return;
    const known = new Set(items.value.map((item) => item.id));
    items.value = [...items.value, ...(page.items || []).filter((item) => !known.has(item.id))];
    nextCursor.value = page.next_cursor ?? null;
  } catch {
    if (current === generation) listError.value = true;
  } finally {
    if (current === generation) loadingMore.value = false;
  }
}
// Clearing walks the whole unfiltered history before deleting anything.
async function clearFinished() {
  if (clearing.value) return;
  clearing.value = true;
  clearError.value = false;
  try {
    const ids: string[] = [];
    let cursor: string | undefined;
    do {
      const page = await api.history({ cursor });
      for (const run of page.items || []) if (terminal.has(run.status)) ids.push(run.id);
      cursor = page.next_cursor || undefined;
    } while (cursor);
    for (const id of ids) await api.deleteHistoryRun(id);
    confirmClear.value = false;
    invalidateHistory("search");
    toast(u("deletedToast"), { tone: "ok" });
  } catch {
    clearError.value = true;
  } finally {
    clearing.value = false;
  }
}
function record(item: HistoryItem) {
  return {
    id: item.id, title: item.display_title || item.question, path: `/runs/${item.id}`, date: item.created_at,
    count: item.result_count, status: item.status, active: !terminal.has(item.status),
  };
}
function target(item: HistoryItem) {
  return ["completed", "completed_with_warnings"].includes(item.status) ? `/runs/${item.id}/results` : `/runs/${item.id}`;
}
onMounted(() => void refresh());
onBeforeUnmount(() => {
  generation += 1;
  listController?.abort();
  if (timer) clearTimeout(timer);
});
</script>

<template>
  <main class="page">
    <div class="toolbar">
      <div class="ig" style="max-width: 360px">
        <Icon name="search" />
        <input v-model="searchInput" type="search" :placeholder="u('historySearch')" :aria-label="u('historySearch')" />
      </div>
      <span v-if="pageState === 'loaded'" class="sm muted" data-testid="history-matched">{{ countText }}</span>
      <div class="row end" style="gap: 8px">
        <button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="u('refresh')" :title="u('refresh')" :disabled="refreshing" @click="refresh(true)"><Icon :name="refreshing ? 'loader' : 'refresh'" /></button>
        <button class="btn btn-outline btn-sm danger" type="button" :disabled="pageState !== 'loaded' || !canClear" @click="confirmClear = true"><Icon name="trash" />{{ u("clearFinished") }}</button>
        <RouterLink class="btn btn-sm" to="/search"><Icon name="plus" />{{ u("newSearch") }}</RouterLink>
      </div>
    </div>

    <div v-if="pageState === 'error'" class="alert" role="alert"><Icon name="fail" /><p class="alert-title">{{ u("loadError") }}</p><div class="alert-act"><button class="btn btn-outline btn-sm" type="button" @click="refresh()">{{ u("retry") }}</button></div></div>
    <div v-else-if="pageState === 'loaded' && !items.length" class="empty">
      <span class="empty-media"><Icon name="text-search" size="lg" /></span>
      <p class="empty-title">{{ searchQuery ? u("noMatches") : u("emptySearches") }}</p>
      <p v-if="!searchQuery" class="empty-desc">{{ u("emptySearchesDesc") }}</p>
      <RouterLink v-if="!searchQuery" class="btn btn-sm" style="margin-top: 8px" to="/search"><Icon name="plus" />{{ u("newSearch") }}</RouterLink>
      <button v-else class="btn btn-outline btn-sm" style="margin-top: 8px" type="button" @click="searchInput = ''">{{ u("clearFilters") }}</button>
    </div>
    <div v-else class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>{{ u("colQuestion") }}</th>
            <th class="shrink">{{ u("colSource") }}</th>
            <th class="shrink">{{ u("colStatus") }}</th>
            <th class="shrink r">{{ u("colResults") }}</th>
            <th class="shrink" aria-sort="descending"><span class="th-sort static">{{ u("colCreated") }}<Icon name="chevron-down" size="sm" /></span></th>
            <th class="shrink"><span class="sr-only">{{ u("colActions") }}</span></th>
          </tr>
        </thead>
        <tbody v-if="pageState === 'loading'">
          <tr v-for="index in 5" :key="index"><td style="min-width: 300px"><span class="skeleton" style="height: 16px; width: 70%"></span></td><td><span class="skeleton" style="height: 14px; width: 64px"></span></td><td><span class="skeleton" style="height: 18px; width: 64px"></span></td><td></td><td><span class="skeleton" style="height: 14px; width: 72px"></span></td><td></td></tr>
        </tbody>
        <tbody v-else>
          <tr v-for="item in items" :key="item.id">
            <td style="min-width: 300px"><RouterLink class="medium" :to="target(item)">{{ item.display_title || item.question }}</RouterLink></td>
            <td class="muted">{{ sourceName(item.source) }}</td>
            <td><StatusBadge :status="item.status" :label="u(`st_${item.status}` as 'st_queued')" /></td>
            <td class="r num" :class="{ muted: !terminal.has(item.status) || !['completed', 'completed_with_warnings'].includes(item.status) }">{{ ["completed", "completed_with_warnings"].includes(item.status) ? item.result_count.toLocaleString() : "—" }}</td>
            <td class="num muted">{{ short(item.created_at) }}</td>
            <td>
              <RecordMenu module="search" :record="record(item)" @changed="refresh(true)">
                <RouterLink class="opt" role="menuitem" data-menu-item :to="`/runs/${item.id}`" :data-testid="`history-flow-${item.id}`"><Icon name="text-search" />{{ u("tabRun") }}</RouterLink>
                <RouterLink v-if="['completed', 'completed_with_warnings'].includes(item.status)" class="opt" role="menuitem" data-menu-item :to="`/runs/${item.id}/results`" :data-testid="`history-results-${item.id}`"><Icon name="file-text" />{{ u("tabResults") }}</RouterLink>
              </RecordMenu>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="nextCursor && items.length" class="row" style="justify-content: center"><button class="btn btn-outline btn-sm" type="button" :disabled="loadingMore" @click="loadMore"><Icon v-if="loadingMore" name="loader" />{{ u("loadMore") }}</button></div>
    <p v-if="listError && pageState === 'loaded'" class="xs danger-text" role="alert">{{ u("loadError") }}</p>

    <AppDialog v-if="confirmClear" :title="u('clearFinishedTitle')" :description="u('clearFinishedDesc')" :busy="clearing" @close="confirmClear = false">
      <p v-if="clearError" class="help danger-text" role="alert">{{ u("actionFailed") }}</p>
      <template #footer>
        <button class="btn btn-outline btn-sm" type="button" :disabled="clearing" @click="confirmClear = false">{{ u("cancel") }}</button>
        <button class="btn btn-destructive btn-sm" type="button" :disabled="clearing" @click="clearFinished"><Icon v-if="clearing" name="loader" />{{ u("clearFinished") }}</button>
      </template>
    </AppDialog>
  </main>
</template>
