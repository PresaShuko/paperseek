<script setup lang="ts">
import { onMounted } from "vue";

import { api } from "../../api/client";
import { useLocale } from "../../locales";
import { loadResults, runState } from "../../state/run";

const { t } = useLocale();
onMounted(() => loadResults().catch(() => undefined));
</script>

<template>
  <main class="workspace-view">
    <header class="workspace-header">
      <div><div class="section-kicker">{{ t("results") }}</div><h2>{{ runState.run?.question || t("noRun") }}</h2></div>
      <div v-if="runState.run" class="result-jump-actions">
        <a class="result-export-button" :href="api.exportUrl(runState.run.id, 'csv')">{{ t("exportCsv") }}</a>
        <a class="secondary-button" :href="api.exportUrl(runState.run.id, 'json')">{{ t("exportJson") }}</a>
      </div>
    </header>
    <p v-if="!runState.results.length" class="m4-empty">{{ t("noResults") }}</p>
    <section class="m4-results-list">
      <article v-for="paper in runState.results" :key="`${paper.rank}-${paper.title}`" class="workflow-card m4-result-card">
        <div class="m4-result-rank">#{{ paper.rank }}</div>
        <div class="m4-result-copy">
          <h3>{{ paper.title }}</h3>
          <p class="history-meta">{{ paper.authors_text || paper.authors?.join('; ') }} · {{ paper.year || paper.publish_year }} · {{ paper.venue || paper.source }}</p>
          <p>{{ paper.abstract }}</p>
          <p class="m4-reason">{{ paper.reasoning || paper.relevance_reason }}</p>
          <div class="m4-result-links">
            <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener">Record</a>
            <a v-if="paper.pdf_url" :href="paper.pdf_url" target="_blank" rel="noopener">PDF</a>
            <span>{{ paper.citation_count ?? paper.citations ?? 0 }} {{ t("citations") }}</span>
          </div>
        </div>
        <strong class="m4-score">{{ paper.score ?? paper.relevance_score ?? "—" }}</strong>
      </article>
    </section>
  </main>
</template>
