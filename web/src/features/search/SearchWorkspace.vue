<script setup lang="ts">
// /search renders the create page; /runs/:id renders the run page.
import RunPage from "./RunPage.vue";
import SearchCreate from "./SearchCreate.vue";

withDefaults(defineProps<{ mode: "edit" | "run"; submissionEnabled?: boolean; externalRecovery?: boolean }>(), { submissionEnabled: true });
</script>

<template>
  <SearchCreate v-if="mode === 'edit'" :submission-enabled="submissionEnabled" />
  <RunPage v-else :external-recovery="externalRecovery" />
</template>
