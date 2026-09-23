<script setup lang="ts">
import { computed } from "vue";

import type { RunDetail, RunEvent } from "../../api/types";
import { useLocale } from "../../locales";

const props = defineProps<{
  run: RunDetail | null;
  events: RunEvent[];
}>();

const { t } = useLocale();

const workflowCompleted = computed(() => {
  for (let index = props.events.length - 1; index >= 0; index -= 1) {
    if (props.events[index].event_type === "workflow.completed") return props.events[index].payload || {};
  }
  return null;
});

// Result count comes from the server run record first, then the commit event.
const resultCount = computed(() => {
  if (props.run?.result_count !== undefined) return props.run.result_count;
  if (workflowCompleted.value?.result_count !== undefined) return Number(workflowCompleted.value.result_count);
  return null;
});

const warningCount = computed(() => {
  if (props.run?.warnings?.length) return props.run.warnings.length;
  if (workflowCompleted.value?.warning_count !== undefined) return Number(workflowCompleted.value.warning_count);
  return 0;
});
</script>

<template>
  <div class="stage-rich" data-testid="stage-results-audit">
    <p v-if="resultCount === null" class="stage-empty">{{ t("noResultsYet") }}</p>
    <template v-else>
      <div class="metric-row">
        <div class="metric"><strong>{{ resultCount }}</strong><span>{{ t("resultCount") }}</span></div>
        <div v-if="warningCount" class="metric"><strong>{{ warningCount }}</strong><span>{{ t("warnings") }}</span></div>
      </div>
    </template>
  </div>
</template>
