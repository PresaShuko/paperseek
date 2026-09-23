<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { api } from "../../api/client";
import type { RunEvent } from "../../api/types";
import { useLocale } from "../../locales";

type Disclosure = "auto" | "manually_open" | "manually_closed";

const props = withDefaults(defineProps<{
  runId: string;
  events: RunEvent[];
  terminal?: boolean;
  idPrefix?: string;
}>(), { idPrefix: "system-log", terminal: false });

const { t } = useLocale();
const disclosure = ref<Disclosure>("auto");
const copied = ref(false);
let copiedTimer: ReturnType<typeof setTimeout> | null = null;

// §12: collapsed by default; a real error auto-opens once; terminal runs fold
// back; a manual choice always wins. Resets when a different run is shown.
watch(() => props.runId, () => {
  disclosure.value = "auto";
  copied.value = false;
});

const hasError = computed(() => props.events.some((event) => /failed|error/.test(event.event_type)));
const open = computed(() => {
  if (disclosure.value === "manually_open") return true;
  if (disclosure.value === "manually_closed") return false;
  return hasError.value && !props.terminal;
});

function toggle(): void {
  disclosure.value = open.value ? "manually_closed" : "manually_open";
}

function openPanel(): void {
  disclosure.value = "manually_open";
}

defineExpose({ openPanel });

const eventCount = computed(() => props.events.length);
const lastSequence = computed(() => props.events[props.events.length - 1]?.sequence ?? 0);

const systemLog = computed(() => props.events.map((event) => {
  const parsed = Date.parse(event.occurred_at || "");
  const time = Number.isNaN(parsed) ? "--:--:--" : new Date(parsed).toTimeString().slice(0, 8);
  return `${String(event.sequence).padStart(6, "0")} ${time} ${event.event_type} ${JSON.stringify(event.payload)}`;
}).join("\n"));

async function copyDiagnostics(): Promise<void> {
  const lines = [
    `run_id: ${props.runId}`,
    `events: ${eventCount.value}`,
    `last_event_sequence: ${lastSequence.value}`,
  ].join("\n");
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
  <section class="log-panel" :class="{ 'is-open': open }" :data-testid="idPrefix" :aria-label="t('systemLog')">
    <div class="log-header">
      <button
        type="button"
        class="log-toggle"
        :data-testid="`${idPrefix}-toggle`"
        :aria-expanded="open"
        :aria-controls="`${idPrefix}-output`"
        @click="toggle"
      >
        <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
        <span>{{ t("systemLog") }}</span>
        <span v-if="hasError" class="log-error-badge">{{ t("systemLogHasError") }}</span>
      </button>
      <div class="log-actions">
        <span class="log-fact" :title="t('events')"><span class="sr-only">{{ t("events") }}: </span><span data-testid="event-count">{{ eventCount }}</span></span>
        <span class="log-fact" :title="t('lastSequence')"><span class="sr-only">{{ t("lastSequence") }}: </span>#<span data-testid="last-event-sequence">{{ lastSequence }}</span></span>
        <button class="log-utility" type="button" data-testid="copy-diagnostics" @click="copyDiagnostics">
          {{ copied ? t("diagnosticsCopied") : t("copyDiagnostics") }}
        </button>
        <slot name="log-export" :content="systemLog" :run-id="runId">
          <a class="log-utility" data-testid="system-log-export" :href="api.logUrl(runId)">{{ t("exportLog") }}</a>
        </slot>
        <code class="log-run-id">{{ runId || "—" }}</code>
      </div>
    </div>
    <pre v-if="open" :id="`${idPrefix}-output`" class="log-output" data-testid="system-log-audit">{{ systemLog }}</pre>
  </section>
</template>
