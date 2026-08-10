<script setup lang="ts">
import { useLocale } from "../locales";

const { language, setLanguage, t } = useLocale();
const tabs = [
  ["search", "/", "search"],
  ["results", "/results", "results"],
  ["citationMap", "/citation-map", "citation-map"],
  ["history", "/history", "history"],
] as const;
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <div class="mark" aria-hidden="true"><img src="/paperseek-mark.png" alt="" /></div>
      <div class="brand-copy">
        <h1 class="brand-title">PaperSeek</h1>
        <div class="brand-subtitle">{{ t("subtitle") }}</div>
      </div>
      <a class="docs-nav-button" href="https://docs.paperseek.xyz/" target="_blank" rel="noopener">{{ t("docs") }}</a>
    </div>
    <nav class="mode-tabs" aria-label="Workspace section">
      <RouterLink
        v-for="([label, path, name]) in tabs"
        :key="name"
        :to="path"
        class="tab"
        :class="{ active: $route.name === name, muted: $route.name !== name }"
      >{{ t(label) }}</RouterLink>
    </nav>
    <div class="status-strip">
      <div class="language-switch" role="group" aria-label="Language">
        <button :class="{ active: language === 'en' }" type="button" @click="setLanguage('en')">EN</button>
        <button :class="{ active: language === 'zh' }" type="button" @click="setLanguage('zh')">中文</button>
      </div>
      <strong>{{ t("ready") }}</strong>
      <span class="ready-dot" aria-hidden="true"></span>
    </div>
  </header>
</template>
