<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { useLocale } from "../../locales";
import { cancelRun, recoverRun, runState, stopRunRecovery, type StageKey } from "../../state/run";
import WorkflowStages from "./WorkflowStages.vue";

const props = defineProps<{ externalRecovery?: boolean }>();
const route = useRoute();
const { runMessage, sourceName, t } = useLocale();
const runId = computed(() => String(route.params.runId || ""));
const pageState = ref<"loading" | "error" | "loaded">("loading");
const diagnosticsOpen = ref(false);
const status = computed(() => runState.run?.status || "");
const isActiveRun = computed(() => ["queued", "running", "cancelling"].includes(status.value));
const canStop = computed(() => ["queued", "running"].includes(status.value) || runState.cancelPending);

const stageLabels: Array<[StageKey, string]> = [
  ["query", "queryStage"],
  ["search", "searchStage"],
  ["ranking", "rankingStage"],
  ["results", "resultsStage"],
];
const activeStage = computed<StageKey | null>(
  () => (Object.keys(runState.stages) as StageKey[]).find((key) => runState.stages[key] === "active") || null,
);
const activeStageLabel = computed(() => {
  const found = stageLabels.find(([key]) => key === activeStage.value);
  return found ? t(found[1]) : "";
});

// Mobile sticky stage bar elapsed time; same server-time derivation as the stages (§6).
const now = ref(Date.now());
const timer = setInterval(() => {
  now.value = Date.now();
}, 1000);
onBeforeUnmount(() => clearInterval(timer));
const activeStageElapsed = computed(() => {
  if (!activeStage.value) return "";
  const startedAt = runState.stageStartedAt[activeStage.value];
  if (!startedAt) return "";
  const started = Date.parse(startedAt);
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
});

function scrollToCurrentStage(): void {
  if (!activeStage.value) return;
  document
    .querySelector(`[data-testid="stage-${activeStage.value}"]`)
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

const statusBadgeClass = computed(() => {
  if (status.value === "failed" || status.value === "cancelled") return "badge--danger";
  if (["completed", "completed_with_warnings"].includes(status.value)) return "badge--success";
  if (isActiveRun.value) return "badge--accent";
  return "";
});

async function stop(): Promise<void> {
  try {
    await cancelRun(runId.value);
  } catch (error) {
    if (!(error instanceof Error && error.name === "AbortError")) {
      runState.error = error instanceof Error ? error.message : "cancel_unavailable";
    }
  }
}

async function load(value: string): Promise<void> {
  if (!value) return;
  pageState.value = "loading";
  try {
    await recoverRun(value);
    if (runId.value === value) pageState.value = "loaded";
  } catch (error) {
    if (runId.value === value && !(error instanceof Error && error.name === "AbortError")) {
      runState.error = error instanceof Error ? error.message : "run_unavailable";
      pageState.value = "error";
    }
  }
}

watch(runId, (value) => {
  diagnosticsOpen.value = false;
  if (!props.externalRecovery) void load(value);
}, { immediate: true });

onBeforeUnmount(() => { if (!props.externalRecovery) stopRunRecovery(); });
</script>

<template>
  <div class="workbench">
    <div class="workbench-pane workbench-pane--config">
      <div v-if="pageState === 'loading' && !runState.run" class="state-block" data-testid="run-loading">
        <span>{{ t("active") }}…</span>
      </div>
      <div v-else-if="pageState === 'error' && !runState.run" class="state-block state-block--error" role="alert">
        <strong>{{ t("loadError") }}</strong>
        <span>{{ t(runState.error || "run_unavailable") }}</span>
        <button class="button" type="button" @click="load(runId)">{{ t("retry") }}</button>
      </div>
      <div v-else class="run-panel">
        <div class="run-panel-primary" data-testid="run-primary-summary">
          <div>
            <div class="section-kicker">{{ t("search") }}</div>
            <h2 class="run-panel-question">{{ runState.run?.question || t("run_unavailable") }}</h2>
          </div>
          <span class="badge" :class="statusBadgeClass"><strong data-testid="run-status">{{ t(status) }}</strong></span>
          <p v-if="runState.run?.error_code" class="alert" role="alert">{{ runMessage(runState.run.error_code, "error") }}</p>
          <dl class="run-panel-facts">
            <div class="fact"><dt>{{ t("dataSource") }}</dt><dd>{{ sourceName(runState.run?.source || "") }}</dd></div>
            <div class="fact"><dt>{{ t("resultCount") }}</dt><dd>{{ runState.run?.result_count ?? 0 }}</dd></div>
          </dl>
          <ul v-if="runState.run?.warnings?.length" class="run-warnings" data-testid="run-warnings">
            <li v-for="warning in runState.run.warnings" :key="warning">{{ runMessage(warning) }}</li>
          </ul>
          <button
            v-if="canStop"
            class="button button--danger"
            type="button"
            :disabled="runState.cancelPending"
            @click="stop"
          >{{ runState.cancelPending ? t("stopping") : t("stop") }}</button>
          <div
            v-if="isActiveRun && runState.connection !== 'connected'"
            class="connection-notice"
            data-testid="connection-notice"
            role="status"
          >
            {{ runState.connection === "offline" ? t("connectionOffline") : t("connectionReconnecting") }}
          </div>
        </div>
        <details class="run-diagnostics" data-testid="run-diagnostics" :open="diagnosticsOpen">
          <summary
            data-testid="run-diagnostics-toggle"
            :aria-expanded="diagnosticsOpen"
            @click.prevent="diagnosticsOpen = !diagnosticsOpen"
          >{{ t("diagnosticInformation") }}</summary>
          <dl class="run-panel-facts">
            <div class="fact"><dt>{{ t("runIdentifier") }}</dt><dd><code>{{ runId }}</code></dd></div>
            <div class="fact"><dt>{{ t("events") }}</dt><dd data-testid="event-count">{{ runState.events.length }}</dd></div>
            <div class="fact"><dt>{{ t("lastSequence") }}</dt><dd data-testid="last-event-sequence">{{ runState.lastEventSequence }}</dd></div>
          </dl>
        </details>
      </div>
    </div>
    <div class="workbench-pane workbench-pane--audit">
      <button
        v-if="activeStage && isActiveRun"
        class="mobile-stage-bar"
        type="button"
        :aria-label="`${t('goToCurrentStage')}: ${activeStageLabel}`"
        @click="scrollToCurrentStage"
      >
        <span class="nav-run-dot" aria-hidden="true"></span>
        <span>{{ activeStageLabel }}</span>
        <span v-if="activeStageElapsed" class="stage-elapsed">{{ activeStageElapsed }}</span>
      </button>
      <WorkflowStages>
        <template v-if="$slots['log-export']" #log-export="scope"><slot name="log-export" v-bind="scope" /></template>
      </WorkflowStages>
    </div>
  </div>
</template>
