<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "../../api/client";
import type { RunDetail } from "../../api/types";
import { useLocale } from "../../locales";
import { selectRun } from "../../state/run";

const { t } = useLocale();
const items = ref<RunDetail[]>([]);
const selected = ref<RunDetail | null>(null);

onMounted(async () => {
  items.value = await api.history().catch(() => []);
});

async function choose(item: RunDetail): Promise<void> {
  selected.value = await api.run(item.id).catch(() => item);
  selectRun(selected.value);
}
</script>

<template>
  <main class="workspace-view">
    <header class="workspace-header"><div><div class="section-kicker">{{ t("history") }}</div><h2>PaperSeek</h2></div></header>
    <p v-if="!items.length" class="m4-empty">{{ t("noHistory") }}</p>
    <section v-else class="history-layout">
      <div class="history-list">
        <button
          v-for="item in items"
          :key="item.id"
          class="history-run-button"
          :class="{ active: selected?.id === item.id }"
          type="button"
          @click="choose(item)"
        ><strong>{{ item.question }}</strong><span>{{ item.source }} · {{ t(item.status) }}</span></button>
      </div>
      <article class="history-detail-panel" data-testid="history-detail">
        <template v-if="selected">
          <div class="section-kicker">{{ t("runDetail") }}</div>
          <h3>{{ selected.question }}</h3>
          <div class="history-meta"><span>{{ selected.source }}</span><span>{{ t(selected.status) }}</span><span>{{ selected.result_count || 0 }} {{ t("results") }}</span></div>
          <code>{{ selected.id }}</code>
        </template>
        <p v-else>{{ t("runDetail") }}</p>
      </article>
    </section>
  </main>
</template>
