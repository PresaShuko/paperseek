<script setup lang="ts">
// Create-page entry kept for embedders.
import SearchCreate from "./SearchCreate.vue";

withDefaults(defineProps<{ submissionEnabled?: boolean }>(), { submissionEnabled: true });
</script>

<template>
  <SearchCreate :submission-enabled="submissionEnabled" />
</template>
