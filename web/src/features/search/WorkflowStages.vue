<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch, watchEffect } from "vue";

import { useLocale } from "../../locales";
import { api } from "../../api/client";
import { runState, type StageKey } from "../../state/run";

type Disclosure = "auto" | "manually_open" | "manually_closed";
type DisclosureKey = StageKey | "log";
type StepStatus = "pending" | "current" | "done" | "degraded" | "failed";

interface StepRow {
  id: string;
  status: StepStatus;
  detail: string;
  progress: { current: number; total: number } | null;
}

interface StructuredRow {
  sequence: number;
  label: string;
  detail: string;
}

const { t } = useLocale();
const stages: Array<[StageKey, string, string]> = [
  ["query", "01", "queryStage"],
  ["search", "02", "searchStage"],
  ["ranking", "03", "rankingStage"],
  ["results", "04", "resultsStage"],
];

// Three-state disclosure per stage, valid only within the current run (§6).
const disclosure = reactive<Record<DisclosureKey, Disclosure>>({
  query: "auto",
  search: "auto",
  ranking: "auto",
  results: "auto",
  log: "auto",
});

function resetDisclosure(): void {
  for (const key of Object.keys(disclosure) as DisclosureKey[]) disclosure[key] = "auto";
}

watch(() => runState.run?.id, resetDisclosure);

// A newly failed stage always opens once, even if the user closed it before;
// a manual close after that failure is respected (§6 priority order).
for (const key of ["query", "search", "ranking", "results"] as StageKey[]) {
  watch(() => runState.stages[key], (next, previous) => {
    if (next === "failed" && previous !== "failed") disclosure[key] = "auto";
  });
}

function eventStage(event: { event_type: string; stage: string }): StageKey | null {
  const type = event.event_type;
  if (type === "query.started" || type === "query.planned" || type === "query.failed") return "query";
  if (type === "query.progress" || type === "query.portfolio_recorded") return "search";
  if (/^(retrieval|citation|ranking|enrichment)\./.test(type)) return "ranking";
  if (/^(final\.|workflow\.completed)/.test(type)) return "results";
  return null;
}

function eventsFor(key: StageKey) {
  return runState.events.filter((event) => eventStage(event) === key);
}

function eventLabel(eventType: string): string {
  const labels: Record<string, string> = {
    "query.started": "eventQueryStarted",
    "query.planned": "eventQueryPlanned",
    "query.progress": "eventQueryProgress",
    "query.portfolio_recorded": "eventQueryPortfolio",
    "retrieval.started": "eventRetrievalStarted",
    "retrieval.progress": "eventRetrievalProgress",
    "retrieval.completed": "eventRetrievalCompleted",
    "retrieval.degraded": "eventRetrievalDegraded",
    "retrieval.failed": "eventRetrievalFailed",
    "citation.started": "eventCitationStarted",
    "citation.progress": "eventCitationProgress",
    "citation.completed": "eventCitationCompleted",
    "citation.skipped": "eventCitationSkipped",
    "citation.degraded": "eventCitationDegraded",
    "ranking.started": "eventRankingStarted",
    "ranking.batch_completed": "eventRankingProgress",
    "ranking.completed": "eventRankingCompleted",
    "ranking.degraded": "eventRankingDegraded",
    "ranking.failed": "eventRankingFailed",
    "enrichment.started": "eventEnrichmentStarted",
    "enrichment.progress": "eventEnrichmentProgress",
    "enrichment.completed": "eventEnrichmentCompleted",
    "enrichment.skipped": "eventEnrichmentSkipped",
    "enrichment.degraded": "eventEnrichmentDegraded",
    "workflow.completed": "eventWorkflowCompleted",
    "workflow.recovery": "eventRecoveryApplied",
  };
  return t(labels[eventType] || "progressUpdated");
}

function localizedDecision(value: unknown): string {
  const key = `decision_${String(value || "recorded")}`;
  const localized = t(key);
  return localized === key ? t("decisionRecorded") : localized;
}

function localizedFailure(code: unknown): string {
  const key = String(code || "operation_failed");
  const localized = t(key);
  return localized === key ? t("operationFailed") : localized;
}

function eventDetail(event: { event_type: string; payload?: Record<string, unknown> }): string {
  const payload = event.payload || {};
  if (event.event_type === "query.started") {
    return payload.target_min === undefined ? t("progressStarted") : `${t("targetMinimum")}: ${Number(payload.target_min)}`;
  }
  if (event.event_type === "query.planned") {
    return [payload.intent, payload.current_query].filter(Boolean).map(String).join(" · ");
  }
  if (event.event_type === "query.progress") {
    return `#${Number(payload.iteration ?? 0)} · ${localizedDecision(payload.decision)} · ${t("sourceHits")} ${Number(payload.hit_count ?? 0)} · ${t("candidates")} ${Number(payload.total ?? 0)}`;
  }
  if (event.event_type === "query.portfolio_recorded") {
    return `${String(payload.query || payload.view_id || "")} · ${t("sourceHits")} ${Number(payload.hit_count ?? 0)}`;
  }
  if (event.event_type.startsWith("retrieval.")) {
    if (/failed/.test(event.event_type)) return localizedFailure(payload.code);
    if (/degraded/.test(event.event_type)) return t("degraded");
    const current = Number(payload.completed_lanes ?? 0);
    const total = Number(payload.total_lanes ?? (Array.isArray(payload.lanes) ? payload.lanes.length : 0));
    const loaded = Number(payload.candidate_count ?? 0);
    const fused = Number(payload.total_candidates ?? loaded);
    return `${t("retrievalLanes")} ${current} / ${total} · ${t("loadedCandidates")} ${loaded} · ${t("fusedCandidates")} ${fused}`;
  }
  if (event.event_type.startsWith("citation.")) {
    if (/skipped/.test(event.event_type)) return t("not_requested");
    if (/degraded/.test(event.event_type)) return t("degraded");
    return `${t("processedSeeds")} ${Number(payload.processed_seeds ?? 0)} / ${Number(payload.seed_count ?? 0)} · ${t("candidates")} ${Number(payload.added_candidates ?? payload.candidate_count ?? 0)}`;
  }
  if (event.event_type.startsWith("ranking.")) {
    if (/failed/.test(event.event_type)) return localizedFailure(payload.code);
    if (/degraded/.test(event.event_type)) return t("degraded");
    const current = Number(payload.completed_batches ?? 0);
    const total = Number(payload.batch_count ?? 0);
    const scored = Number(payload.scored_count ?? 0);
    const candidates = Number(payload.candidate_count ?? 0);
    return `${t("rankingBatches")} ${current} / ${total} · ${t("sentToLlm")} ${scored || candidates}`;
  }
  if (event.event_type.startsWith("enrichment.")) {
    if (/skipped/.test(event.event_type)) return t("not_requested");
    if (/degraded/.test(event.event_type)) return t("degraded");
    return `${t("enrichedAbstracts")} ${Number(payload.enriched_count ?? payload.current ?? 0)} / ${Number(payload.total ?? payload.request_count ?? 0)}`;
  }
  if (event.event_type === "workflow.completed") {
    return `${t("finalOutput")}: ${Number(payload.result_count ?? 0)} · ${t("warnings")}: ${Number(payload.warning_count ?? 0)}`;
  }
  if (event.event_type === "workflow.recovery") return t("recoveryApplied");
  return t("progressUpdated");
}

function structuredEventsFor(key: StageKey): StructuredRow[] {
  return eventsFor(key).map((event) => ({
    sequence: event.sequence,
    label: eventLabel(event.event_type),
    detail: eventDetail(event),
  }));
}

function progressRows(prefix: string): StructuredRow[] {
  return runState.events
    .filter((event) => event.event_type.startsWith(`${prefix}.`))
    .map((event) => ({ sequence: event.sequence, label: eventLabel(event.event_type), detail: eventDetail(event) }));
}

function lastPayload(prefix: string): Record<string, unknown> | null {
  for (let index = runState.events.length - 1; index >= 0; index -= 1) {
    const event = runState.events[index];
    if (event.event_type.startsWith(prefix)) return event.payload || {};
  }
  return null;
}

const activeStage = computed<StageKey | null>(
  () => (Object.keys(runState.stages) as StageKey[]).find((key) => runState.stages[key] === "active") || null,
);
const failedStage = computed<StageKey | null>(
  () => (Object.keys(runState.stages) as StageKey[]).find((key) => runState.stages[key] === "failed") || null,
);
const runCancelled = computed(() => runState.run?.status === "cancelled");
const runTerminal = computed(
  () => ["completed", "completed_with_warnings", "failed", "cancelled"].includes(runState.run?.status || ""),
);
const resultsComplete = computed(
  () => ["completed", "completed_with_warnings"].includes(runState.run?.status || ""),
);

function isOpen(key: DisclosureKey): boolean {
  const manual = disclosure[key];
  if (manual === "manually_open") return true;
  if (manual === "manually_closed") return false;
  if (key === "log") return false;
  if (runState.stages[key] === "failed") return true;
  // "Current stage" only exists while the run is actually live; a stale active
  // stage in a terminal run stays collapsed (§6).
  return runState.stages[key] === "active" && !runTerminal.value;
}

function toggleDisclosure(key: DisclosureKey): void {
  disclosure[key] = isOpen(key) ? "manually_closed" : "manually_open";
}

// Elapsed time derives from the server event time, recomputed on a timer (§6).
const now = ref(Date.now());
const timer = setInterval(() => {
  now.value = Date.now();
}, 1000);
onBeforeUnmount(() => clearInterval(timer));

function elapsed(key: StageKey): string {
  if (runState.stages[key] !== "active") return "";
  const startedAt = runState.stageStartedAt[key];
  if (!startedAt) return "";
  const started = Date.parse(startedAt);
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function statusText(key: StageKey): string {
  const value = runState.stages[key];
  if (runCancelled.value && (value === "active" || value === "idle")) return t("cancelled");
  return t(value === "active" ? "active" : value);
}

function badgeClass(key: StageKey): string {
  const value = runState.stages[key];
  if (value === "failed") return "badge--danger";
  if (value === "complete") return "badge--success";
  if (value === "active" && !runCancelled.value) return "badge--accent";
  return "";
}

const queryPlanned = computed(() => lastPayload("query.planned"));
const queryViews = computed<Array<{ view_id?: string; purpose?: string }>>(() => {
  const views = queryPlanned.value?.query_views;
  return Array.isArray(views) ? views : [];
});
const iterations = computed(() => runState.events
  .filter((event) => event.event_type === "query.progress")
  .map((event) => ({ sequence: event.sequence, ...(event.payload || {}) } as { sequence: number } & Record<string, unknown>)));
const retrievalCompleted = computed(() => {
  for (let index = runState.events.length - 1; index >= 0; index -= 1) {
    if (runState.events[index].event_type === "retrieval.completed") return runState.events[index].payload || {};
  }
  return null;
});
const workflowCompleted = computed(() => {
  for (let index = runState.events.length - 1; index >= 0; index -= 1) {
    if (runState.events[index].event_type === "workflow.completed") return runState.events[index].payload || {};
  }
  return null;
});

function summaryLine(key: StageKey): string {
  if (key === "query") {
    const planned = queryPlanned.value;
    if (!planned) return "";
    return String(planned.intent || planned.current_query || "");
  }
  if (key === "search") {
    const latest = iterations.value[iterations.value.length - 1];
    if (!latest) return "";
    const iterationCount = iterations.value.reduce((max, item) => Math.max(max, Number(item.iteration) || 0), 0);
    const parts = [
      `${iterationCount} ${t("iterations")}`,
      localizedDecision(latest.decision),
      `${t("sourceHits")} ${Number(latest.hit_count ?? 0)}`,
      `${t("candidates")} ${Number(latest.total ?? 0)}`,
    ];
    if (latest.query) parts.push(String(latest.query));
    return parts.join(" · ");
  }
  if (key === "ranking") {
    const parts: string[] = [];
    if (retrievalCompleted.value) parts.push(`${t("fusedCandidates")} ${Number(retrievalCompleted.value.total_candidates ?? 0)}`);
    const ranking = lastPayload("ranking.completed") || lastPayload("ranking.");
    if (ranking && ranking.scored_count !== undefined) parts.push(`${t("sentToLlm")} ${Number(ranking.scored_count)}`);
    return parts.join(" · ");
  }
  if (workflowCompleted.value) {
    const payload = workflowCompleted.value;
    const warnings = Number(payload.warning_count ?? 0);
    return `${Number(payload.result_count ?? 0)} ${t("resultCount")}${warnings ? ` · ${warnings} ${t("warnings")}` : ""}`;
  }
  return "";
}

const rankingSteps = computed<StepRow[]>(() => {
  const rows: StepRow[] = [];
  const retrievalEvents = runState.events.filter((event) => event.event_type.startsWith("retrieval."));
  if (retrievalEvents.length) {
    const progress = lastPayload("retrieval.progress");
    const completed = retrievalCompleted.value;
    const failed = retrievalEvents.some((event) => event.event_type === "retrieval.failed");
    const degradedPayload = lastPayload("retrieval.degraded");
    let status: StepStatus = "current";
    if (failed) status = "failed";
    else if (completed) status = "done";
    else if (degradedPayload && !completed) status = "degraded";
    const detail = completed
      ? `${t("fusedCandidates")} ${Number(completed.total_candidates ?? 0)} · ${t("loadedCandidates")} ${Number(completed.candidate_count ?? 0)}`
      : progress
        ? `${Number(progress.completed_lanes ?? 0)} / ${Number(progress.total_lanes ?? 0)} · ${Number(progress.candidate_count ?? 0)} ${t("candidates")}`
        : "";
    rows.push({
      id: "stepMultiLane",
      status,
      detail,
      progress: progress && !completed
        ? { current: Number(progress.completed_lanes ?? 0), total: Number(progress.total_lanes ?? 0) }
        : null,
    });
  }
  const citationEvents = runState.events.filter((event) => event.event_type.startsWith("citation."));
  if (citationEvents.length) {
    const latest = citationEvents[citationEvents.length - 1];
    const payload = latest.payload || {};
    let status: StepStatus = "current";
    let detail = "";
    if (latest.event_type === "citation.completed") {
      status = "done";
      detail = `${Number(payload.added_candidates ?? 0)} / ${Number(payload.candidate_count ?? 0)} ${t("candidates")}`;
    } else if (latest.event_type === "citation.skipped") {
      status = "done";
      detail = t("not_requested");
    } else if (latest.event_type === "citation.degraded") {
      status = "degraded";
      detail = String(payload.code || t("degraded"));
    } else {
      detail = `${Number(payload.processed_seeds ?? 0)} / ${Number(payload.seed_count ?? 0)}`;
    }
    rows.push({
      id: "stepCitation",
      status,
      detail,
      progress: status === "current"
        ? { current: Number(payload.processed_seeds ?? 0), total: Number(payload.seed_count ?? 0) }
        : null,
    });
  }
  const rankingEvents = runState.events.filter((event) => event.event_type.startsWith("ranking."));
  if (rankingEvents.length) {
    const completedPayload = lastPayload("ranking.completed");
    const failedPayload = lastPayload("ranking.failed");
    const batch = lastPayload("ranking.batch_completed") || lastPayload("ranking.started");
    const degradedPayload = lastPayload("ranking.degraded");
    let status: StepStatus = "current";
    if (failedPayload) status = "failed";
    else if (completedPayload) status = "done";
    else if (degradedPayload) status = "degraded";
    const current = Number(batch?.completed_batches ?? 0);
    const total = Number(batch?.batch_count ?? 0);
    const detail = failedPayload
      ? `${localizedFailure(failedPayload.code)}${failedPayload.failed_candidates !== undefined ? ` · ${t("failedCandidates")} ${Number(failedPayload.failed_candidates)}` : ""}`
      : completedPayload
      ? `${Number(completedPayload.scored_count ?? 0)} / ${Number(completedPayload.candidate_count ?? 0)}${Number(completedPayload.warning_count ?? 0) ? ` · ${Number(completedPayload.warning_count)} ${t("warnings")}` : ""}`
      : batch
        ? `${current} / ${total}`
        : "";
    rows.push({
      id: "stepLlmRanking",
      status,
      detail,
      progress: status === "current" && total ? { current, total } : null,
    });
  }
  const enrichmentEvents = runState.events.filter((event) => event.event_type.startsWith("enrichment."));
  if (enrichmentEvents.length) {
    const latest = enrichmentEvents[enrichmentEvents.length - 1];
    const payload = latest.payload || {};
    let status: StepStatus = "current";
    let detail = "";
    if (latest.event_type === "enrichment.completed") {
      status = "done";
      detail = `${Number(payload.enriched_count ?? 0)} / ${Number(payload.total ?? payload.request_count ?? 0)}`;
    } else if (latest.event_type === "enrichment.skipped") {
      status = "done";
      detail = t("not_requested");
    } else if (latest.event_type === "enrichment.degraded") {
      status = "degraded";
      detail = String(payload.code || t("degraded"));
    } else {
      detail = `${Number(payload.current ?? 0)} / ${Number(payload.total ?? payload.request_count ?? 0)}`;
    }
    rows.push({
      id: "stepEnrichment",
      status,
      detail,
      progress: status === "current"
        ? { current: Number(payload.current ?? 0), total: Number(payload.total ?? payload.request_count ?? 0) }
        : null,
    });
  }
  return rows;
});

function stepIcon(status: StepStatus): string {
  if (status === "done") return "step-icon--done";
  if (status === "current") return "step-icon--current";
  if (status === "failed") return "step-icon--failed";
  if (status === "degraded") return "step-icon--degraded";
  return "step-icon--pending";
}

function stepStatusText(status: StepStatus): string {
  if (status === "done") return t("complete");
  if (status === "current") return t("active");
  if (status === "failed") return t("failed");
  if (status === "degraded") return t("degraded");
  return t("idle");
}

// Normal progress stays structured; raw machine facts live only in the folded audit/log sections.
const retrievalProgress = computed(() => progressRows("retrieval"));
const rankingProgress = computed(() => progressRows("ranking"));
const enrichmentProgress = computed(() => progressRows("enrichment"));

function portfolioDetail(item: Record<string, unknown>): string {
  const facts = [item.purpose, item.query].filter(Boolean).map(String);
  if (item.status) facts.push(t(String(item.status)));
  if (item.hit_count !== undefined) facts.push(`${t("sourceHits")} ${Number(item.hit_count)}`);
  if (item.added_unique !== undefined) facts.push(`${t("uniqueCandidates")} ${Number(item.added_unique)}`);
  return facts.join(" · ");
}

const logHasError = computed(() => runState.events.some((event) => /failed|error/.test(event.event_type)));
const systemLog = computed(() => runState.events.map((event) =>
  `${String(event.sequence).padStart(6, "0")} ${event.event_type} ${JSON.stringify(event.payload)}`,
).join("\n"));

function openLog(): void {
  disclosure.log = "manually_open";
}

// Dedicated concise announcer; the workflow container itself is not a live region (§8).
const announcement = ref("");
let lastAnnouncedStage: string | null = null;
let lastAnnouncedStatus = "";
watchEffect(() => {
  const status = runState.run?.status || "";
  if (status && status !== lastAnnouncedStatus && ["completed", "completed_with_warnings", "failed", "cancelled"].includes(status)) {
    announcement.value = t(status);
    lastAnnouncedStatus = status;
    lastAnnouncedStage = null;
    return;
  }
  const stage = activeStage.value;
  if (stage && stage !== lastAnnouncedStage) {
    const label = stages.find(([key]) => key === stage)?.[2] || "";
    announcement.value = `${t("announceStage")}: ${t(label)}`;
    lastAnnouncedStage = stage;
  }
});
</script>

<template>
  <div class="workflow">
    <p class="sr-only" aria-live="polite">{{ announcement }}</p>
    <template v-for="([key, number, label]) in stages" :key="key">
      <details
        class="stage-card"
        :class="{ 'stage-card--active': runState.stages[key] === 'active' }"
        :data-testid="`stage-${key}`"
        :data-state="runState.stages[key]"
        :open="isOpen(key)"
      >
        <summary
          class="stage-summary"
          :data-testid="`stage-${key}-toggle`"
          :aria-expanded="isOpen(key)"
          @click.prevent="toggleDisclosure(key)"
        >
          <span class="stage-number" aria-hidden="true">{{ number }}</span>
          <span class="stage-heading">
            <span class="stage-title">
              {{ t(label) }}
              <span v-if="runState.run" class="badge" :class="badgeClass(key)">{{ statusText(key) }}</span>
            </span>
            <span v-if="summaryLine(key)" class="stage-summary-line">{{ summaryLine(key) }}</span>
          </span>
          <span class="stage-meta">
            <span v-if="elapsed(key)" class="stage-elapsed" :data-testid="`stage-${key}-elapsed`">{{ elapsed(key) }}</span>
            <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
          </span>
        </summary>
        <div class="stage-body">
          <template v-if="key === 'ranking' && rankingSteps.length">
            <ol class="step-list" :data-testid="`stage-${key}-audit`">
              <li v-for="step in rankingSteps" :key="step.id" class="step-row">
                <span class="step-icon" :class="stepIcon(step.status)" aria-hidden="true">
                  <svg v-if="step.status === 'done'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
                  <svg v-else-if="step.status === 'current'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                  <svg v-else-if="step.status === 'failed' || step.status === 'degraded'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 9 4 4m0-4-4 4M12 3 2 21h20L12 3z" /></svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /></svg>
                </span>
                <span class="step-name">{{ t(step.id) }}</span>
                <span class="step-detail" :class="{ 'step-detail--accent': step.status === 'current' }">{{ stepStatusText(step.status) }}<template v-if="step.detail"> · {{ step.detail }}</template></span>
                <span v-if="step.progress && step.progress.total" class="step-progress" role="progressbar" :aria-valuenow="step.progress.current" :aria-valuemax="step.progress.total">
                  <span :style="{ width: `${Math.min(100, (step.progress.current / step.progress.total) * 100)}%` }"></span>
                </span>
              </li>
            </ol>
          </template>
          <ol v-else class="audit-list" :data-testid="`stage-${key}-audit`">
            <li v-for="row in structuredEventsFor(key)" :key="row.sequence" class="audit-item structured-event-row">
              <strong>{{ row.label }}</strong>
              <span v-if="row.detail">{{ row.detail }}</span>
            </li>
          </ol>
          <p v-if="runCancelled && runState.stages[key] !== 'complete'" class="field-help">{{ t("stageCancelledNote") }}</p>
          <div v-if="failedStage === key" class="stage-recovery">
            <RouterLink class="button button--small" to="/search">{{ t("checkConfigAction") }}</RouterLink>
            <button class="button button--small" type="button" @click="openLog">{{ t("viewLog") }}</button>
            <RouterLink class="button button--small" to="/search">{{ t("backToSearch") }}</RouterLink>
            <RouterLink class="button button--small" to="/search">{{ t("newSearch") }}</RouterLink>
          </div>
        </div>
      </details>
      <div v-if="key === 'results' && resultsComplete" class="stage-entries">
        <RouterLink class="button" :to="`/runs/${runState.run!.id}/results`">{{ t("viewResults") }}</RouterLink>
        <RouterLink class="button" :to="`/runs/${runState.run!.id}/citation-map`">{{ t("viewCitationMap") }}</RouterLink>
      </div>
    </template>

    <details v-if="retrievalProgress.length" class="stage-card" data-testid="retrieval-progress">
      <summary class="stage-summary" data-testid="retrieval-progress-toggle">
        <span class="stage-heading"><span class="stage-title">{{ t("retrievalProgress") }}</span></span>
        <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </summary>
      <div class="stage-body" data-testid="retrieval-progress-rows">
        <ol class="audit-list" data-testid="retrieval-progress-audit">
          <li v-for="row in retrievalProgress" :key="row.sequence" class="audit-item structured-event-row"><strong>{{ row.label }}</strong><span>{{ row.detail }}</span></li>
        </ol>
      </div>
    </details>
    <details v-if="rankingProgress.length" class="stage-card" data-testid="ranking-progress">
      <summary class="stage-summary" data-testid="ranking-progress-toggle">
        <span class="stage-heading"><span class="stage-title">{{ t("rankingProgress") }}</span></span>
        <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </summary>
      <div class="stage-body" data-testid="ranking-progress-rows">
        <ol class="audit-list" data-testid="ranking-progress-audit">
          <li v-for="row in rankingProgress" :key="row.sequence" class="audit-item structured-event-row"><strong>{{ row.label }}</strong><span>{{ row.detail }}</span></li>
        </ol>
      </div>
    </details>
    <details v-if="enrichmentProgress.length" class="stage-card" data-testid="enrichment-progress">
      <summary class="stage-summary" data-testid="enrichment-progress-toggle">
        <span class="stage-heading"><span class="stage-title">{{ t("enrichmentProgress") }}</span></span>
        <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </summary>
      <div class="stage-body" data-testid="enrichment-progress-rows">
        <ol class="audit-list" data-testid="enrichment-progress-audit">
          <li v-for="row in enrichmentProgress" :key="row.sequence" class="audit-item structured-event-row"><strong>{{ row.label }}</strong><span>{{ row.detail }}</span></li>
        </ol>
      </div>
    </details>

    <details v-if="runState.events.length" class="log-card" data-testid="system-log" :open="isOpen('log')">
      <summary data-testid="system-log-toggle" :aria-expanded="isOpen('log')" @click.prevent="toggleDisclosure('log')">
        <span class="log-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
          {{ t("systemLog") }}
          <span v-if="logHasError" class="badge badge--danger">{{ t("systemLogHasError") }}</span>
        </span>
        <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </summary>
      <div class="log-body">
        <div class="log-toolbar">
          <a class="button button--small" data-testid="system-log-export" :href="api.logUrl(runState.run!.id)">{{ t("exportLog") }}</a>
        </div>
        <pre class="log-content" data-testid="system-log-audit">{{ systemLog }}</pre>
      </div>
    </details>

    <details v-if="runState.audit" class="stage-card" data-testid="query-portfolio">
      <summary class="stage-summary" data-testid="query-portfolio-toggle">
        <span class="stage-heading"><span class="stage-title">{{ t("queryPortfolio") }}</span></span>
        <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </summary>
      <div class="stage-body">
        <ul class="audit-list" data-testid="query-portfolio-audit">
          <li v-for="(item, index) in (runState.audit.query_portfolio || [])" :key="String(item.view_id || index)" class="audit-item structured-event-row">
            <strong><code>{{ item.view_id || `#${index + 1}` }}</code></strong>
            <span>{{ portfolioDetail(item) }}</span>
          </li>
          <li v-if="!(runState.audit.query_portfolio || []).length" class="audit-item">{{ t("noQueryPortfolio") }}</li>
        </ul>
      </div>
    </details>
    <details v-if="runState.audit" class="stage-card" data-testid="technical-audit-section">
      <summary class="stage-summary" data-testid="technical-audit-toggle">
        <span class="stage-heading"><span class="stage-title">{{ t("technicalAudit") }}</span></span>
        <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </summary>
      <div class="stage-body"><pre class="log-content" data-testid="technical-audit">{{ JSON.stringify({
        loop_decisions: runState.audit.loop_decisions,
        candidate_queue: runState.audit.candidate_queue,
      }, null, 2) }}</pre></div>
    </details>
    <details v-if="runState.audit" class="stage-card" data-testid="candidate-recovery-section">
      <summary class="stage-summary" data-testid="candidate-recovery-toggle">
        <span class="stage-heading"><span class="stage-title">{{ t("candidateRecovery") }}</span></span>
        <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </summary>
      <div class="stage-body"><pre class="log-content" data-testid="candidate-recovery-audit">{{ JSON.stringify({
        candidate_lifecycle: runState.audit.candidate_lifecycle,
        recovery: runState.audit.recovery,
      }, null, 2) }}</pre></div>
    </details>

    <div v-if="runState.error" class="alert" role="alert">
      <strong>{{ t(runState.error) }}</strong>
    </div>
  </div>
</template>
