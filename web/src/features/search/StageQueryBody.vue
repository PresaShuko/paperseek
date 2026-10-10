<script setup lang="ts">
import { computed } from "vue";
import type { RunEvent } from "../../api/types";
import Disclosure from "../../components/Disclosure.vue";
import { useLocale } from "../../locales";

const props = defineProps<{ events: RunEvent[]; source: string }>();
const { sourceName, t } = useLocale();
const planned = computed<Record<string, unknown> | null>(() => props.events.findLast((event) => event.event_type === "query.planned")?.payload || null);
const list = (key: string) => (Array.isArray(planned.value?.[key]) ? (planned.value![key] as unknown[]).map(String) : []);
const rows = computed(() => {
  const plan = planned.value;
  if (!plan) return [];
  const result: Array<{ label: string; values: string[] }> = [];
  if (plan.question_type) result.push({ label: t("questionType"), values: [String(plan.question_type)] });
  for (const [key, label] of [["likely_synonyms", "likelySynonyms"], ["adjacent_concepts", "adjacentConcepts"], ["boundaries", "boundaries"], ["ambiguities", "ambiguities"]]) {
    if (list(key).length) result.push({ label: t(label), values: list(key) });
  }
  if (plan.adjustment_strategy) result.push({ label: t("adjustmentStrategy"), values: [String(plan.adjustment_strategy)] });
  return result;
});
const views = computed<Array<Record<string, unknown>>>(() => (Array.isArray(planned.value?.query_views) ? (planned.value!.query_views as Array<Record<string, unknown>>) : []));
</script>

<template>
  <div class="stack" style="gap: 12px" data-testid="stage-query-audit">
    <p v-if="!events.length" class="sm muted">{{ t("noQueryYet") }}</p>
    <template v-else>
      <div v-if="planned?.intent" class="stack" style="gap: 4px"><span class="xs muted medium">{{ t("interpretedIntent") }}</span><p class="sm">{{ planned.intent }}</p></div>
      <div v-if="list('core_concepts').length" class="stack" style="gap: 6px">
        <span class="xs muted medium">{{ t("coreConcepts") }}</span>
        <div class="chips"><span v-for="concept in list('core_concepts')" :key="concept" class="badge badge-outline">{{ concept }}</span></div>
      </div>
      <div v-if="planned?.current_query" class="stack" style="gap: 4px">
        <span class="xs muted medium">{{ t("currentQuery") }} · {{ sourceName(source) }}</span>
        <code class="code">{{ planned.current_query }}</code>
      </div>
      <Disclosure v-if="rows.length || views.length" :items="[{ key: 'intent', label: t('fullIntentAnalysis'), testid: 'stage-query-intent-toggle' }]">
        <template #intent><dl class="kv" style="grid-template-columns: auto minmax(0, 1fr)">
          <template v-for="row in rows" :key="row.label"><dt>{{ row.label }}</dt><dd style="text-align: left">{{ row.values.join("; ") }}</dd></template>
          <template v-for="(view, index) in views" :key="String(view.view_id || index)"><dt class="mono">{{ view.view_id || `#${index + 1}` }}</dt><dd style="text-align: left">{{ view.purpose }}</dd></template>
        </dl></template>
      </Disclosure>
    </template>
  </div>
</template>
