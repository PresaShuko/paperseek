<script setup lang="ts">
import { computed, ref } from "vue";

import type { RunAudit, RunEvent } from "../../api/types";
import { useLocale } from "../../locales";
import { localizedDecision, portfolioDetail } from "./workflow-format";

const props = defineProps<{
  events: RunEvent[];
  audit: RunAudit | null;
  stageActive: boolean;
}>();

const { t } = useLocale();
const portfolioOpen = ref(false);
const auditOpen = ref(false);
const openIterations = ref<Set<number>>(new Set());

const iterations = computed<Array<Record<string, unknown> & { sequence: number }>>(() =>
  props.events
    .filter((event) => event.event_type === "query.progress")
    .map((event) => ({ sequence: event.sequence, ...(event.payload || {}) })),
);

const latest = computed(() => iterations.value[iterations.value.length - 1] || null);
const iterationTotal = computed(() =>
  iterations.value.reduce((max, row) => Math.max(max, Number(row.iteration) || 0), 0),
);
const currentQuery = computed(() => String(latest.value?.query || ""));

// The newest iteration starts expanded while the stage is live or accepted (legacy rule).
function isIterationOpen(index: number): boolean {
  if (openIterations.value.has(index)) return true;
  if (openIterations.value.has(-1 - index)) return false;
  const last = index === iterations.value.length - 1;
  return last && (props.stageActive || String(latest.value?.decision || "") === "accept");
}

function toggleIteration(index: number): void {
  const next = new Set(openIterations.value);
  const open = isIterationOpen(index);
  next.delete(index);
  next.delete(-1 - index);
  next.add(open ? -1 - index : index);
  openIterations.value = next;
}

const portfolio = computed<Array<Record<string, unknown>>>(() =>
  Array.isArray(props.audit?.query_portfolio) ? props.audit.query_portfolio : []);

const auditJson = computed(() => JSON.stringify({
  loop_decisions: props.audit?.loop_decisions,
  candidate_queue: props.audit?.candidate_queue,
}, null, 2));
</script>

<template>
  <div class="stage-rich" data-testid="stage-search-audit">
    <p v-if="!iterations.length" class="stage-empty">{{ t("waitingFirstResponse") }}</p>
    <template v-else>
      <div class="metric-row">
        <div class="metric"><strong>{{ iterationTotal }}</strong><span>{{ t("iterations") }}</span></div>
        <div class="metric"><strong>{{ Number(latest?.hit_count ?? 0) }}</strong><span>{{ t("sourceHits") }}</span></div>
        <div class="metric"><strong>{{ latest ? localizedDecision(t, latest.decision) : "—" }}</strong><span>{{ t("finalAction") }}</span></div>
      </div>
      <div v-if="currentQuery" class="query-output">
        <span class="detail-label">{{ t("currentQuery") }}</span>
        <code>{{ currentQuery }}</code>
      </div>
      <div class="iteration-list">
        <section v-for="(row, index) in iterations" :key="row.sequence" class="iteration-row" data-testid="iteration-row">
          <button
            type="button"
            class="iteration-toggle"
            :aria-expanded="isIterationOpen(index)"
            :aria-controls="`iteration-body-${row.sequence}`"
            @click="toggleIteration(index)"
          >
            <span class="iteration-meta">
              <strong>{{ t("iterationLabel").replace("{n}", String(row.iteration ?? index + 1)) }}</strong>
              <span class="action-pill" :data-action="String(row.decision || 'recorded')">{{ localizedDecision(t, row.decision) }}</span>
              <span>{{ t("sourceHits") }} {{ Number(row.hit_count ?? 0) }}</span>
            </span>
            <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': isIterationOpen(index) }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
          </button>
          <div v-if="isIterationOpen(index)" :id="`iteration-body-${row.sequence}`" class="iteration-body">
            <code v-if="row.query">{{ row.query }}</code>
            <p v-if="row.message || row.reason">{{ row.message || row.reason }}</p>
          </div>
        </section>
      </div>
    </template>
    <template v-if="audit">
      <section class="stage-disclosure">
        <button
          type="button"
          class="stage-disclosure-toggle"
          data-testid="stage-search-portfolio-toggle"
          :aria-expanded="portfolioOpen"
          aria-controls="stage-search-portfolio"
          @click="portfolioOpen = !portfolioOpen"
        >
          <span>{{ t("queryPortfolio") }}</span>
          <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': portfolioOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
        </button>
        <div v-if="portfolioOpen" id="stage-search-portfolio" class="stage-disclosure-body">
          <ul class="audit-list" data-testid="query-portfolio-audit">
            <li v-for="(item, index) in portfolio" :key="String(item.view_id || index)" class="audit-item structured-event-row">
              <strong><code>{{ item.view_id || `#${index + 1}` }}</code></strong>
              <span>{{ portfolioDetail(t, item) }}</span>
            </li>
            <li v-if="!portfolio.length" class="audit-item">{{ t("noQueryPortfolio") }}</li>
          </ul>
        </div>
      </section>
      <section class="stage-disclosure">
        <button
          type="button"
          class="stage-disclosure-toggle"
          data-testid="stage-search-audit-toggle"
          :aria-expanded="auditOpen"
          aria-controls="stage-search-technical-audit"
          @click="auditOpen = !auditOpen"
        >
          <span>{{ t("technicalAudit") }}</span>
          <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': auditOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
        </button>
        <div v-if="auditOpen" id="stage-search-technical-audit" class="stage-disclosure-body">
          <pre class="log-content" data-testid="technical-audit">{{ auditJson }}</pre>
        </div>
      </section>
    </template>
  </div>
</template>
