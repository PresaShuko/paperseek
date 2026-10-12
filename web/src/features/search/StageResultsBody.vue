<script setup lang="ts">
import { computed } from "vue";
import type { RunDetail, RunEvent } from "../../api/types";
import { useLocale } from "../../locales";

const props = defineProps<{ run: RunDetail | null; events: RunEvent[] }>();
const { t } = useLocale();
const completed = computed(() => props.events.findLast((event) => event.event_type === "workflow.completed")?.payload || null);
const resultCount = computed(() => props.run?.result_count ?? (completed.value?.result_count !== undefined ? Number(completed.value.result_count) : null));
const warningCount = computed(() => props.run?.warnings?.length || Number(completed.value?.warning_count ?? 0));
</script>

<template>
  <div data-testid="stage-results-audit">
    <p v-if="resultCount === null" class="sm muted">{{ t("noResultsYet") }}</p>
    <div v-else class="metrics" style="max-width: 360px">
      <div class="metric"><span class="medium num">{{ resultCount.toLocaleString() }}</span><span class="xs muted">{{ t("resultCount") }}</span></div>
      <div class="metric"><span class="medium num">{{ warningCount }}</span><span class="xs muted">{{ t("warnings") }}</span></div>
    </div>
  </div>
</template>
