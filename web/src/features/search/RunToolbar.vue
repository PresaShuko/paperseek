<script setup lang="ts">
// Shared toolbar for one search: Progress ↔ Results tabs, status line, actions.
import { computed } from "vue";
import type { RunDetail } from "../../api/types";
import Icon, { type IconName } from "../../components/Icon.vue";
import { useLocale } from "../../locales";
import { useUi } from "../../locales/ui";

const props = defineProps<{ run: RunDetail | null; tab: "run" | "results"; resultCount?: number | null }>();
const { t, sourceName } = useLocale();
const u = useUi();
const done = computed(() => ["completed", "completed_with_warnings"].includes(props.run?.status || ""));
const icon = computed<IconName | null>(() => ({
  running: "loader", cancelling: "loader", completed: "ok", completed_with_warnings: "warn", failed: "fail", cancelled: "circle-minus",
} as Record<string, IconName>)[props.run?.status || ""] || null);
const line = computed(() => {
  const run = props.run;
  if (!run) return "";
  const budget = String(run.config_snapshot?.search_budget || "");
  return [
    u(`st_${run.status}` as "st_queued"),
    sourceName(run.source),
    budget ? t(budget) : "",
    String(run.config_snapshot?.llm?.model || ""),
  ].filter(Boolean).join(" · ");
});
const count = computed(() => props.resultCount ?? props.run?.result_count ?? null);
</script>

<template>
  <div class="toolbar">
    <div class="tabs" role="tablist" :aria-label="u('runTabs')">
      <RouterLink v-if="run" class="tab" :class="{ active: tab === 'run' }" role="tab" :aria-selected="tab === 'run'" :to="`/runs/${run.id}`">{{ u("tabRun") }}</RouterLink>
      <RouterLink v-if="run && done" class="tab" :class="{ active: tab === 'results' }" role="tab" :aria-selected="tab === 'results'" :to="`/runs/${run.id}/results`">{{ u("tabResults") }}<span v-if="count != null" class="badge badge-secondary">{{ count.toLocaleString() }}</span></RouterLink>
      <span v-else class="tab" role="tab" aria-selected="false" aria-disabled="true" :title="u('resultsAfterDone')">{{ u("tabResults") }}</span>
    </div>
    <span class="sm muted row" style="gap: 6px; margin-left: 8px; flex-wrap: nowrap; min-width: 0"><Icon v-if="icon" :name="icon" size="sm" /><span class="truncate">{{ line }}</span></span>
    <div class="row end" style="gap: 8px"><slot /></div>
  </div>
</template>
