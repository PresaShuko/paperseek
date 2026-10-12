<script setup lang="ts">
// Radio list of past searches; unusable ones stay visible but disabled with a reason.
import { onBeforeUnmount, ref, watch } from "vue";
import { api } from "../../api/client";
import type { HistoryItem } from "../../api/types";
import Icon from "../../components/Icon.vue";
import { useUi } from "../../locales/ui";
import { useDates } from "./format";

const props = withDefaults(defineProps<{ minimum?: number; selected?: string; label: string }>(), { minimum: 2 });
const emit = defineEmits<{ select: [id: string, item: HistoryItem] }>();
const u = useUi();
const { day } = useDates();
const query = ref("");
const items = ref<HistoryItem[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const error = ref(false);
let controller: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0;

async function load(more = false) {
  const own = ++generation;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = false;
  try {
    const page = await api.history({ query: query.value.trim() || undefined, cursor: more ? cursor.value : undefined }, controller.signal);
    if (own !== generation) return;
    items.value = more ? [...items.value, ...(page.items || [])] : page.items || [];
    cursor.value = page.next_cursor ?? null;
  } catch {
    if (own === generation && !controller.signal.aborted) error.value = true;
  } finally {
    if (own === generation) loading.value = false;
  }
}
watch(query, () => {
  clearTimeout(timer);
  timer = setTimeout(() => void load(), 200);
});
void load();
onBeforeUnmount(() => {
  generation++;
  controller?.abort();
  clearTimeout(timer);
});
function reason(item: HistoryItem): string {
  if (!["completed", "completed_with_warnings"].includes(item.status)) return u("needsCompletion");
  if (item.result_count < props.minimum) return u("tooFewResults");
  return "";
}
function keydown(event: KeyboardEvent) {
  if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
  event.preventDefault();
  const rows = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="radio"]:not([aria-disabled="true"])'));
  const index = rows.indexOf(document.activeElement as HTMLButtonElement);
  const next = rows[(index + (event.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length];
  next?.focus();
  next?.click();
}
</script>

<template>
  <div class="stack" style="gap: 8px">
    <div class="ig"><Icon name="search" /><input v-model="query" type="search" :placeholder="u('findSearch')" :aria-label="u('findSearch')" /></div>
    <div v-if="error" class="alert" role="alert"><Icon name="fail" /><p class="alert-title">{{ u("loadError") }}</p><div class="alert-act"><button class="btn btn-outline btn-sm" type="button" @click="load()">{{ u("retry") }}</button></div></div>
    <div v-else-if="loading && !items.length" class="pick" aria-busy="true">
      <div v-for="index in 3" :key="index" class="pick-row"><span class="radio"></span><span class="skeleton grow" style="height: 14px"></span></div>
    </div>
    <p v-else-if="!items.length" class="sm muted" style="padding: 8px 0">{{ query ? u("noMatches") : u("noSearchesYet") }}</p>
    <div v-else class="pick" role="radiogroup" :aria-label="label" style="max-height: 360px; overflow-y: auto; scrollbar-gutter: stable" @keydown="keydown">
      <button
        v-for="item in items"
        :key="item.id"
        class="pick-row"
        type="button"
        role="radio"
        :aria-checked="selected === item.id"
        :aria-disabled="reason(item) ? 'true' : undefined"
        :tabindex="selected === item.id || (!selected && !reason(item)) ? 0 : -1"
        @click="!reason(item) && emit('select', item.id, item)"
      >
        <span class="radio"></span>
        <span class="grow truncate sm medium">{{ item.display_title || item.question }}</span>
        <span v-if="reason(item)" class="xs muted">{{ reason(item) }}</span>
        <span v-else class="xs muted num">{{ u("papersShort", { n: item.result_count.toLocaleString() }) }} · {{ day(item.created_at) }}</span>
      </button>
      <button v-if="cursor" class="pick-row" type="button" style="justify-content: center" :disabled="loading" @click="load(true)"><Icon v-if="loading" name="loader" size="sm" /><span class="sm muted">{{ u("loadMore") }}</span></button>
    </div>
  </div>
</template>
