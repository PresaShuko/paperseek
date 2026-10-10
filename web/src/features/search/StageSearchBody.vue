<script setup lang="ts">
import { computed, ref } from "vue";
import type { RunAudit, RunEvent } from "../../api/types";
import Disclosure from "../../components/Disclosure.vue";
import Icon from "../../components/Icon.vue";
import { useLocale } from "../../locales";
import { localizedDecision, localizedRefinementStop, portfolioDetail } from "./workflow-format";

const props = defineProps<{ events: RunEvent[]; audit: RunAudit | null; stageActive: boolean }>();
const { t } = useLocale();
const toggled = ref(new Map<number, boolean>());
const iterations = computed(() => props.events
  .filter((event) => event.event_type === "query.progress")
  .map((event) => ({ sequence: event.sequence, ...(event.payload || {}) } as Record<string, unknown> & { sequence: number })));
const latest = computed(() => iterations.value[iterations.value.length - 1] || null);
const stopped = computed(() => props.events.findLast((event) => event.event_type === "query.refinement_stopped")?.payload);
const selected = computed(() => props.events.findLast((event) => event.event_type === "query.selected")?.payload);
const final = computed(() => stopped.value || selected.value || latest.value);
const request = computed(() => props.events.findLast((event) => event.event_type === "query.request_started")?.payload);
const total = computed(() => Math.max(Number(request.value?.iteration) || 0, ...iterations.value.map((row) => Number(row.iteration) || 0)));
const query = computed(() => String(props.events.findLast((event) =>
  ["query.request_started", "query.progress", "query.selected", "query.refinement_stopped"].includes(event.event_type))?.payload?.query || ""));
function open(index: number) {
  const manual = toggled.value.get(index);
  if (manual !== undefined) return manual;
  return index === iterations.value.length - 1 && (props.stageActive || String(latest.value?.decision || "") === "accept");
}
function toggle(index: number) {
  const next = new Map(toggled.value);
  next.set(index, !open(index));
  toggled.value = next;
}
const portfolio = computed<Array<Record<string, unknown>>>(() => (Array.isArray(props.audit?.query_portfolio) ? props.audit!.query_portfolio : []));
const auditJson = computed(() => JSON.stringify({ loop_decisions: props.audit?.loop_decisions, candidate_queue: props.audit?.candidate_queue }, null, 2));
</script>

<template>
  <div class="stack" style="gap: 12px" data-testid="stage-search-audit">
    <p v-if="!iterations.length && !request" class="sm muted">{{ t(stageActive ? "waitingFirstResponse" : "notExecuted") }}</p>
    <template v-else>
      <div class="metrics">
        <div class="metric"><span class="medium num">{{ total }}</span><span class="xs muted">{{ t("iterations") }}</span></div>
        <div class="metric"><span class="medium num">{{ Number(final?.total ?? 0).toLocaleString() }}</span><span class="xs muted">{{ t("sourceTotal") }}</span></div>
        <div class="metric"><span class="medium num">{{ Number(final?.hit_count ?? 0).toLocaleString() }}</span><span class="xs muted">{{ t("retrievedPapers") }}</span></div>
        <div class="metric"><span class="medium">{{ final ? localizedDecision(t, final.decision) : "—" }}</span><span class="xs muted">{{ t("finalAction") }}</span></div>
      </div>
      <p v-if="stopped" class="sm" role="status" data-testid="refinement-stop-reason">{{ localizedRefinementStop(t, stopped.code) }}</p>
      <p v-if="selected" class="sm" role="status" data-testid="selected-query-reason">{{ t("querySelectionReason").replace("{n}", String(selected.selected_iteration)) }}</p>
      <div v-if="query" class="stack" style="gap: 4px">
        <span class="xs muted medium">{{ t(selected || stopped ? "selectedQuery" : "currentQuery") }}</span>
        <code class="code">{{ query }}</code>
      </div>
      <ol v-if="iterations.length" class="list" style="margin: 0 -10px">
        <li v-for="(row, index) in iterations" :key="row.sequence" data-testid="iteration-row">
          <button class="list-row" type="button" :aria-expanded="open(index)" @click="toggle(index)">
            <Icon name="chevron-right" class="muted" :style="{ transform: open(index) ? 'rotate(90deg)' : undefined }" />
            <span class="sm medium">{{ t("iterationLabel").replace("{n}", String(row.iteration ?? index + 1)) }}</span>
            <span class="badge badge-outline muted">{{ localizedDecision(t, row.decision) }}</span>
            <span class="xs muted num end">{{ t("retrievedPapers") }} {{ Number(row.hit_count ?? 0).toLocaleString() }} · {{ t("sourceTotal") }} {{ Number(row.total ?? 0).toLocaleString() }}</span>
          </button>
          <div v-if="open(index)" class="stack" style="gap: 6px; padding: 2px 10px 8px 34px">
            <code v-if="row.query" class="code">{{ row.query }}</code>
            <p v-if="row.message || row.reason" class="sm muted">{{ row.message || row.reason }}</p>
          </div>
        </li>
      </ol>
    </template>
    <Disclosure v-if="audit" :items="[{ key: 'portfolio', label: t('queryPortfolio'), testid: 'stage-search-portfolio-toggle' }, { key: 'audit', label: t('technicalAudit'), testid: 'stage-search-audit-toggle' }]">
      <template #portfolio>
        <ul class="stack" style="gap: 6px" data-testid="query-portfolio-audit">
          <li v-for="(item, index) in portfolio" :key="String(item.view_id || index)" class="sm"><code class="mono xs">{{ item.view_id || `#${index + 1}` }}</code> <span class="muted">{{ portfolioDetail(t, item) }}</span></li>
          <li v-if="!portfolio.length" class="sm muted">{{ t("noQueryPortfolio") }}</li>
        </ul>
      </template>
      <template #audit><pre class="code" data-testid="technical-audit">{{ auditJson }}</pre></template>
    </Disclosure>
  </div>
</template>
