<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

import { useLocale } from "../locales";
import { runState } from "../state/run";

const { language, setLanguage, t } = useLocale();
const route = useRoute();

const runId = computed(() => (typeof route.params.runId === "string" ? route.params.runId : ""));
const tabs = computed(() => [
  { label: "search", path: "/search", name: "search", disabled: false },
  { label: "results", path: runId.value ? `/runs/${runId.value}/results` : "", name: "results", disabled: !runId.value },
  { label: "citationMap", path: runId.value ? `/runs/${runId.value}/citation-map` : "", name: "citation-map", disabled: !runId.value },
  { label: "history", path: "/history", name: "history", disabled: false },
]);

// Small in-progress marker on the Search tab while the user is elsewhere (§10.5).
const activeRunElsewhere = computed(() => {
  if (!runState.run || !["queued", "running", "cancelling"].includes(runState.run.status)) return false;
  return !["search", "run"].includes(String(route.name));
});

function currentFor(name: string): "page" | undefined {
  if (String(route.name) === name) return "page";
  if (name === "search" && String(route.name) === "run") return "page";
  return undefined;
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-brand">
      <span class="brand-mark" aria-hidden="true"><img src="/paperseek-mark.png" alt="" /></span>
      <span class="brand-copy">
        <h1 class="brand-title">PaperSeek</h1>
        <span class="brand-subtitle">{{ t("subtitle") }}</span>
      </span>
      <a class="docs-link" href="https://docs.paperseek.xyz/" target="_blank" rel="noopener">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
        <span>{{ t("docs") }}</span>
      </a>
    </div>
    <nav class="topbar-nav" :aria-label="t('workspaceNav')">
      <template v-for="tab in tabs" :key="tab.name">
        <RouterLink
          v-if="!tab.disabled"
          :to="tab.path"
          class="nav-tab"
          :aria-current="currentFor(tab.name)"
        >
          <span>{{ t(tab.label) }}</span>
          <span
            v-if="tab.name === 'search' && activeRunElsewhere"
            class="nav-run-dot"
            :title="t('active')"
            aria-hidden="true"
          ></span>
        </RouterLink>
        <span
          v-else
          class="nav-tab nav-tab--disabled"
          role="link"
          tabindex="0"
          aria-disabled="true"
          :aria-label="`${t(tab.label)} — ${t('noRun')}`"
          :title="t('noRun')"
        >{{ t(tab.label) }}</span>
      </template>
    </nav>
    <div class="topbar-side">
      <div class="segmented language-switch" role="group" :aria-label="t('language')">
        <button :class="{ active: language === 'en' }" :aria-pressed="language === 'en'" type="button" @click="setLanguage('en')">EN</button>
        <button :class="{ active: language === 'zh' }" :aria-pressed="language === 'zh'" type="button" @click="setLanguage('zh')">中文</button>
      </div>
    </div>
  </header>
</template>
