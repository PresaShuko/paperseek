<script setup lang="ts">
import { useLocale } from "../../locales";
import { runState, type StageKey } from "../../state/run";

const { t } = useLocale();
const stages: Array<[StageKey, string, string]> = [
  ["query", "01", "queryStage"],
  ["search", "02", "searchStage"],
  ["ranking", "03", "rankingStage"],
  ["results", "04", "resultsStage"],
];
</script>

<template>
  <div class="workflow" aria-live="polite">
    <article
      v-for="([key, number, label]) in stages"
      :key="key"
      class="workflow-card m4-stage"
      :class="`m4-stage-${runState.stages[key]}`"
      :data-testid="`stage-${key}`"
      :data-state="runState.stages[key]"
    >
      <div class="m4-stage-number">{{ number }}</div>
      <div>
        <div class="section-kicker">{{ t(label) }}</div>
        <strong>{{ t(runState.stages[key] === "active" ? "active" : runState.stages[key]) }}</strong>
      </div>
      <span class="m4-stage-dot" aria-hidden="true"></span>
    </article>
    <section v-if="runState.error" class="config-alert-list" role="alert">
      {{ runState.error }}
    </section>
  </div>
</template>
