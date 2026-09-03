<script setup lang="ts">
import AppHeader from "./components/AppHeader.vue";
import { useLocale } from "./locales";

const { t } = useLocale();
</script>

<template>
  <a class="skip-link" href="#main-content">{{ t("skipToContent") }}</a>
  <AppHeader />
  <main id="main-content" class="app-main" tabindex="-1">
    <RouterView />
  </main>
</template>
