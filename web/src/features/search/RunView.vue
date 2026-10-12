<script setup lang="ts">
// Run page entry kept for embedders that recover the run themselves.
import RunPage from "./RunPage.vue";

defineProps<{ externalRecovery?: boolean }>();
</script>

<template>
  <RunPage :external-recovery="externalRecovery" />
</template>
