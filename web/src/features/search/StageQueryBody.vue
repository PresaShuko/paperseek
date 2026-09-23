<script setup lang="ts">
import { computed, ref } from "vue";

import type { RunEvent } from "../../api/types";
import { useLocale } from "../../locales";

const props = defineProps<{
  events: RunEvent[];
  source: string;
}>();

const { sourceName, t } = useLocale();
const intentOpen = ref(false);

const planned = computed<Record<string, unknown> | null>(() => {
  for (let index = props.events.length - 1; index >= 0; index -= 1) {
    if (props.events[index].event_type === "query.planned") return props.events[index].payload || {};
  }
  return null;
});

const intent = computed(() => String(planned.value?.intent || ""));
const currentQuery = computed(() => String(planned.value?.current_query || ""));
const coreConcepts = computed(() => Array.isArray(planned.value?.core_concepts) ? planned.value.core_concepts.map(String) : []);
const queryViews = computed<Array<Record<string, unknown>>>(() =>
  Array.isArray(planned.value?.query_views) ? planned.value.query_views : []);

interface IntentRow {
  label: string;
  values: string[];
}

const intentRows = computed<IntentRow[]>(() => {
  const plan = planned.value;
  if (!plan) return [];
  const rows: IntentRow[] = [];
  const list = (key: string, label: string) => {
    if (Array.isArray(plan[key]) && (plan[key] as unknown[]).length) rows.push({ label, values: (plan[key] as unknown[]).map(String) });
  };
  if (plan.question_type) rows.push({ label: t("questionType"), values: [String(plan.question_type)] });
  list("likely_synonyms", t("likelySynonyms"));
  list("adjacent_concepts", t("adjacentConcepts"));
  list("boundaries", t("boundaries"));
  list("ambiguities", t("ambiguities"));
  if (plan.adjustment_strategy) rows.push({ label: t("adjustmentStrategy"), values: [String(plan.adjustment_strategy)] });
  return rows;
});

const hasIntentDetail = computed(() => intentRows.value.length || queryViews.value.length);
</script>

<template>
  <div class="stage-rich" data-testid="stage-query-audit">
    <p v-if="!events.length" class="stage-empty">{{ t("noQueryYet") }}</p>
    <template v-else>
      <div v-if="intent" class="intent-summary">
        <span class="detail-label">{{ t("interpretedIntent") }}</span>
        <p>{{ intent }}</p>
      </div>
      <div v-if="coreConcepts.length" class="chip-row">
        <span class="detail-label">{{ t("coreConcepts") }}</span>
        <span v-for="concept in coreConcepts" :key="concept" class="chip">{{ concept }}</span>
      </div>
      <div v-if="currentQuery" class="query-output">
        <span class="detail-label">{{ t("currentQuery") }}</span>
        <small>{{ sourceName(source) }}</small>
        <code>{{ currentQuery }}</code>
      </div>
      <section v-if="hasIntentDetail" class="stage-disclosure">
        <button
          type="button"
          class="stage-disclosure-toggle"
          data-testid="stage-query-intent-toggle"
          :aria-expanded="intentOpen"
          aria-controls="stage-query-intent"
          @click="intentOpen = !intentOpen"
        >
          <span>{{ t("fullIntentAnalysis") }}</span>
          <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': intentOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
        </button>
        <div v-if="intentOpen" id="stage-query-intent" class="stage-disclosure-body">
          <div v-for="row in intentRows" :key="row.label" class="intent-detail-group">
            <strong>{{ row.label }}</strong>
            <div v-if="row.values.length > 1" class="chip-row"><span v-for="value in row.values" :key="value" class="chip">{{ value }}</span></div>
            <span v-else>{{ row.values[0] }}</span>
          </div>
          <div v-if="queryViews.length" class="intent-detail-group">
            <strong>{{ t("queryViews") }}</strong>
            <div v-for="(view, index) in queryViews" :key="String(view.view_id || index)" class="query-view-row">
              <code>{{ view.view_id || `#${index + 1}` }}</code>
              <span v-if="view.purpose">{{ view.purpose }}</span>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
