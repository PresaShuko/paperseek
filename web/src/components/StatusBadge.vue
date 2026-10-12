<script setup lang="ts">
// Status = outline badge + icon (spinner running, clock queued, filled ok/warn/fail, minus cancelled).
import { computed } from "vue";
import Icon, { type IconName } from "./Icon.vue";

const props = defineProps<{ status: string; label: string }>();
const icon = computed<IconName>(() => ({
  running: "loader", cancelling: "loader", queued: "clock", completed: "ok",
  completed_with_warnings: "warn", failed: "fail", cancelled: "circle-minus",
} as Record<string, IconName>)[props.status] || "circle-minus");
</script>

<template>
  <span class="badge badge-outline muted"><Icon :name="icon" />{{ label }}</span>
</template>
