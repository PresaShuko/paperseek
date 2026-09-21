<script setup lang="ts">
// Thin wrapper kept for the Hosted alias imports: the externalRecovery prop and
// the log-export slot are forwarded unchanged to the shared workbench (run mode).
import SearchWorkspace from "./SearchWorkspace.vue";

defineProps<{ externalRecovery?: boolean }>();
</script>

<template>
  <SearchWorkspace mode="run" :external-recovery="externalRecovery">
    <template v-if="$slots['log-export']" #log-export="scope"><slot name="log-export" v-bind="scope" /></template>
  </SearchWorkspace>
</template>
