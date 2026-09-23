<script setup lang="ts">
import { computed, ref } from "vue";

import type { RunAudit, RunEvent } from "../../api/types";
import { useLocale } from "../../locales";
import { localizedFailure, progressRows } from "./workflow-format";

type StepStatus = "pending" | "current" | "done" | "degraded" | "failed";

interface StepRow {
  id: string;
  status: StepStatus;
  detail: string;
  progress: { current: number; total: number } | null;
}

const props = defineProps<{
  events: RunEvent[];
  audit: RunAudit | null;
}>();

const { t } = useLocale();
const processOpen = ref(false);
const recoveryOpen = ref(false);

function lastPayload(prefix: string): Record<string, unknown> | null {
  for (let index = props.events.length - 1; index >= 0; index -= 1) {
    const event = props.events[index];
    if (event.event_type.startsWith(prefix)) return event.payload || {};
  }
  return null;
}

const retrievalCompleted = computed(() => lastPayload("retrieval.completed"));
const workflowCompleted = computed(() => lastPayload("workflow.completed"));

// §5.2 number semantics: each metric renders only when its source field exists.
const metrics = computed(() => {
  const rows: Array<{ value: string; label: string }> = [];
  if (retrievalCompleted.value) {
    rows.push({ value: String(Number(retrievalCompleted.value.candidate_count ?? 0)), label: t("loadedCandidates") });
    rows.push({ value: String(Number(retrievalCompleted.value.total_candidates ?? 0)), label: t("fusedCandidates") });
  }
  const ranking = lastPayload("ranking.completed") || lastPayload("ranking.started");
  if (ranking && ranking.candidate_count !== undefined) {
    rows.push({ value: String(Number(ranking.candidate_count)), label: t("sentToLlm") });
  }
  if (workflowCompleted.value && workflowCompleted.value.result_count !== undefined) {
    rows.push({ value: String(Number(workflowCompleted.value.result_count)), label: t("finalOutput") });
  }
  return rows;
});

const rankingSteps = computed<StepRow[]>(() => {
  const rows: StepRow[] = [];
  const retrievalEvents = props.events.filter((event) => event.event_type.startsWith("retrieval."));
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
  const citationEvents = props.events.filter((event) => event.event_type.startsWith("citation."));
  if (citationEvents.length) {
    const latestEvent = citationEvents[citationEvents.length - 1];
    const payload = latestEvent.payload || {};
    let status: StepStatus = "current";
    let detail = "";
    if (latestEvent.event_type === "citation.completed") {
      status = "done";
      detail = `${Number(payload.added_candidates ?? 0)} / ${Number(payload.candidate_count ?? 0)} ${t("candidates")}`;
    } else if (latestEvent.event_type === "citation.skipped") {
      status = "done";
      detail = t("not_requested");
    } else if (latestEvent.event_type === "citation.degraded") {
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
  const rankingEvents = props.events.filter((event) => event.event_type.startsWith("ranking."));
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
      ? `${localizedFailure(t, failedPayload.code)}${failedPayload.failed_candidates !== undefined ? ` · ${t("failedCandidates")} ${Number(failedPayload.failed_candidates)}` : ""}`
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
  const enrichmentEvents = props.events.filter((event) => event.event_type.startsWith("enrichment."));
  if (enrichmentEvents.length) {
    const latestEvent = enrichmentEvents[enrichmentEvents.length - 1];
    const payload = latestEvent.payload || {};
    let status: StepStatus = "current";
    let detail = "";
    if (latestEvent.event_type === "enrichment.completed") {
      status = "done";
      detail = `${Number(payload.enriched_count ?? 0)} / ${Number(payload.total ?? payload.request_count ?? 0)}`;
    } else if (latestEvent.event_type === "enrichment.skipped") {
      status = "done";
      detail = t("not_requested");
    } else if (latestEvent.event_type === "enrichment.degraded") {
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

const processGroups = computed(() => [
  { key: "retrieval", title: t("retrievalProgress"), testid: "retrieval-progress-audit", rows: progressRows(t, props.events, "retrieval") },
  { key: "ranking", title: t("rankingProgress"), testid: "ranking-progress-audit", rows: progressRows(t, props.events, "ranking") },
  { key: "enrichment", title: t("enrichmentProgress"), testid: "enrichment-progress-audit", rows: progressRows(t, props.events, "enrichment") },
].filter((group) => group.rows.length));

const recoveryJson = computed(() => JSON.stringify({
  candidate_lifecycle: props.audit?.candidate_lifecycle,
  recovery: props.audit?.recovery,
}, null, 2));
</script>

<template>
  <div class="stage-rich" data-testid="stage-ranking-audit">
    <p v-if="!events.length" class="stage-empty">{{ t("waitingFirstResponse") }}</p>
    <template v-else>
      <div v-if="metrics.length" class="metric-row">
        <div v-for="metric in metrics" :key="metric.label" class="metric">
          <strong>{{ metric.value }}</strong>
          <span>{{ metric.label }}</span>
        </div>
      </div>
      <ol v-if="rankingSteps.length" class="step-list">
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
      <section v-if="processGroups.length" class="stage-disclosure">
        <button
          type="button"
          class="stage-disclosure-toggle"
          data-testid="stage-ranking-process-toggle"
          :aria-expanded="processOpen"
          aria-controls="stage-ranking-process"
          @click="processOpen = !processOpen"
        >
          <span>{{ t("processDetail") }}</span>
          <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': processOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
        </button>
        <div v-if="processOpen" id="stage-ranking-process" class="stage-disclosure-body">
          <section v-for="group in processGroups" :key="group.key" class="process-group">
            <h4 class="process-heading">{{ group.title }}</h4>
            <ol class="audit-list" :data-testid="group.testid">
              <li v-for="row in group.rows" :key="row.sequence" class="audit-item structured-event-row">
                <strong>{{ row.label }}</strong>
                <span v-if="row.detail">{{ row.detail }}</span>
              </li>
            </ol>
          </section>
        </div>
      </section>
      <section v-if="audit" class="stage-disclosure">
        <button
          type="button"
          class="stage-disclosure-toggle"
          data-testid="stage-ranking-audit-toggle"
          :aria-expanded="recoveryOpen"
          aria-controls="stage-ranking-recovery"
          @click="recoveryOpen = !recoveryOpen"
        >
          <span>{{ t("candidateRecovery") }}</span>
          <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': recoveryOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
        </button>
        <div v-if="recoveryOpen" id="stage-ranking-recovery" class="stage-disclosure-body">
          <pre class="log-content" data-testid="candidate-recovery-audit">{{ recoveryJson }}</pre>
        </div>
      </section>
    </template>
  </div>
</template>
