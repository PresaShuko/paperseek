<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { api } from "../../api/client";
import type { RunVersions } from "../../api/generated";
import type { RunAudit, RunEvent } from "../../api/types";
import { useLocale } from "../../locales";
import { portfolioDetail, progressRows, systemLogText, type StructuredRow } from "./workflow-format";

type TabId = "log" | "process" | "diagnostics";

const props = withDefaults(defineProps<{
  runId: string;
  events: RunEvent[];
  audit: RunAudit | null;
  lastEventSequence?: number;
  versions?: RunVersions | null;
  idPrefix?: string;
}>(), { idPrefix: "run-details", lastEventSequence: undefined, versions: null });

const { t } = useLocale();
const open = ref(false);
const activeTab = ref<TabId>("log");
const copied = ref(false);
let copiedTimer: ReturnType<typeof setTimeout> | null = null;

const tabs: Array<{ id: TabId; label: string }> = [
  { id: "log", label: "runDetailsTabLog" },
  { id: "process", label: "runDetailsTabProcess" },
  { id: "diagnostics", label: "runDetailsTabDiagnostics" },
];

// The entry never auto-opens; a different run resets to the closed default (§12).
watch(() => props.runId, () => {
  open.value = false;
  activeTab.value = "log";
});

function openTab(tab: TabId): void {
  open.value = true;
  activeTab.value = tab;
}

defineExpose({ openTab });

// Manual-activation tabs (W3C APG): arrows/Home/End move focus, Enter/Space activate.
function onTablistKeydown(event: KeyboardEvent): void {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const buttons = Array.from(
    (event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]'),
  );
  if (!buttons.length) return;
  event.preventDefault();
  const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
  let next = current;
  if (event.key === "ArrowRight") next = (current + 1) % buttons.length;
  else if (event.key === "ArrowLeft") next = (current - 1 + buttons.length) % buttons.length;
  else if (event.key === "Home") next = 0;
  else next = buttons.length - 1;
  buttons[next].focus();
}

const systemLog = computed(() => systemLogText(props.events));

const processGroups = computed<Array<{ key: string; title: string; testid: string; rows: StructuredRow[] }>>(() => {
  const groups = [
    { key: "retrieval", title: t("retrievalProgress"), testid: "retrieval-progress-audit", rows: progressRows(t, props.events, "retrieval") },
    { key: "ranking", title: t("rankingProgress"), testid: "ranking-progress-audit", rows: progressRows(t, props.events, "ranking") },
    { key: "enrichment", title: t("enrichmentProgress"), testid: "enrichment-progress-audit", rows: progressRows(t, props.events, "enrichment") },
  ];
  return groups.filter((group) => group.rows.length);
});

const portfolio = computed<Array<Record<string, unknown>>>(() => {
  const items = props.audit?.query_portfolio;
  return Array.isArray(items) ? items : [];
});

const eventCount = computed(() => props.events.length);
const lastSequence = computed(() => props.lastEventSequence ?? props.events[props.events.length - 1]?.sequence ?? 0);
const versionFacts = computed(() => {
  const versions = props.versions;
  if (!versions) return "";
  return Object.entries(versions)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
});

const technicalAuditJson = computed(() => JSON.stringify({
  loop_decisions: props.audit?.loop_decisions,
  candidate_queue: props.audit?.candidate_queue,
}, null, 2));
const candidateRecoveryJson = computed(() => JSON.stringify({
  candidate_lifecycle: props.audit?.candidate_lifecycle,
  recovery: props.audit?.recovery,
}, null, 2));

async function copyDiagnostics(): Promise<void> {
  const lines = [
    `run_id: ${props.runId}`,
    `events: ${eventCount.value}`,
    `last_event_sequence: ${lastSequence.value}`,
    versionFacts.value ? `versions: ${versionFacts.value}` : "",
  ].filter(Boolean).join("\n");
  try {
    await navigator.clipboard.writeText(lines);
    copied.value = true;
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => { copied.value = false; }, 2000);
  } catch {
    // Clipboard can be unavailable (permissions); the facts stay visible for manual copy.
  }
}
</script>

<template>
  <section class="run-details" :data-testid="idPrefix">
    <button
      type="button"
      class="run-details-toggle"
      :data-testid="`${idPrefix}-toggle`"
      :aria-expanded="open"
      :aria-controls="`${idPrefix}-body`"
      @click="open = !open"
    >
      <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      <span>{{ t("runDetails") }}</span>
    </button>
    <div v-if="open" :id="`${idPrefix}-body`" class="run-details-body">
      <div class="run-details-tabs" role="tablist" :aria-label="t('runDetails')" @keydown="onTablistKeydown">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          :id="`${idPrefix}-tab-${tab.id}`"
          type="button"
          role="tab"
          class="run-details-tab"
          :class="{ 'run-details-tab--active': activeTab === tab.id }"
          :data-testid="`${idPrefix}-tab-${tab.id}`"
          :aria-selected="activeTab === tab.id"
          :aria-controls="`${idPrefix}-panel-${tab.id}`"
          :tabindex="activeTab === tab.id ? 0 : -1"
          @click="activeTab = tab.id"
        >{{ t(tab.label) }}</button>
      </div>

      <div
        v-if="activeTab === 'log'"
        :id="`${idPrefix}-panel-log`"
        class="run-details-panel"
        role="tabpanel"
        :aria-labelledby="`${idPrefix}-tab-log`"
        tabindex="0"
      >
        <div class="log-toolbar">
          <slot name="log-export" :content="systemLog" :run-id="runId">
            <a class="button button--small" data-testid="system-log-export" :href="api.logUrl(runId)">{{ t("exportLog") }}</a>
          </slot>
        </div>
        <pre class="log-content" data-testid="system-log-audit">{{ systemLog }}</pre>
      </div>

      <div
        v-else-if="activeTab === 'process'"
        :id="`${idPrefix}-panel-process`"
        class="run-details-panel"
        role="tabpanel"
        :aria-labelledby="`${idPrefix}-tab-process`"
        tabindex="0"
      >
        <section v-for="group in processGroups" :key="group.key" class="run-details-group">
          <h4 class="run-details-heading">{{ group.title }}</h4>
          <ol class="audit-list" :data-testid="group.testid">
            <li v-for="row in group.rows" :key="row.sequence" class="audit-item structured-event-row">
              <strong>{{ row.label }}</strong>
              <span v-if="row.detail">{{ row.detail }}</span>
            </li>
          </ol>
        </section>
        <section v-if="audit" class="run-details-group">
          <h4 class="run-details-heading">{{ t("queryPortfolio") }}</h4>
          <ul class="audit-list" data-testid="query-portfolio-audit">
            <li v-for="(item, index) in portfolio" :key="String(item.view_id || index)" class="audit-item structured-event-row">
              <strong><code>{{ item.view_id || `#${index + 1}` }}</code></strong>
              <span>{{ portfolioDetail(t, item) }}</span>
            </li>
            <li v-if="!portfolio.length" class="audit-item">{{ t("noQueryPortfolio") }}</li>
          </ul>
        </section>
        <p v-if="!processGroups.length && !audit" class="field-help">{{ t("noEventsYet") }}</p>
      </div>

      <div
        v-else
        :id="`${idPrefix}-panel-diagnostics`"
        class="run-details-panel"
        role="tabpanel"
        :aria-labelledby="`${idPrefix}-tab-diagnostics`"
        tabindex="0"
      >
        <dl class="run-panel-facts">
          <div class="fact"><dt>{{ t("runIdentifier") }}</dt><dd><code>{{ runId }}</code></dd></div>
          <div class="fact"><dt>{{ t("events") }}</dt><dd data-testid="event-count">{{ eventCount }}</dd></div>
          <div class="fact"><dt>{{ t("lastSequence") }}</dt><dd data-testid="last-event-sequence">{{ lastSequence }}</dd></div>
          <div v-if="versionFacts" class="fact"><dt>{{ t("versions") }}</dt><dd><code>{{ versionFacts }}</code></dd></div>
        </dl>
        <div class="alert-actions">
          <button class="button button--small" type="button" data-testid="copy-diagnostics" @click="copyDiagnostics">
            {{ copied ? t("diagnosticsCopied") : t("copyDiagnostics") }}
          </button>
        </div>
        <details v-if="audit" class="run-details-raw" data-testid="technical-audit-section">
          <summary data-testid="technical-audit-toggle">{{ t("technicalAudit") }}</summary>
          <pre class="log-content" data-testid="technical-audit">{{ technicalAuditJson }}</pre>
        </details>
        <details v-if="audit" class="run-details-raw" data-testid="candidate-recovery-section">
          <summary data-testid="candidate-recovery-toggle">{{ t("candidateRecovery") }}</summary>
          <pre class="log-content" data-testid="candidate-recovery-audit">{{ candidateRecoveryJson }}</pre>
        </details>
      </div>
    </div>
  </section>
</template>
