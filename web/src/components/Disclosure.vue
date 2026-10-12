<script setup lang="ts">
// A row of ghost "chevron + label" toggles; the open one shows full width below.
import { ref, useId } from "vue";
import Icon from "./Icon.vue";

defineProps<{ items: Array<{ key: string; label: string; testid?: string }> }>();
const open = ref("");
const id = useId();
</script>

<template>
  <div class="stack" style="gap: 8px">
    <div class="row" style="gap: 2px; margin-left: -12px">
      <button
        v-for="item in items"
        :key="item.key"
        class="btn btn-ghost btn-sm"
        type="button"
        :data-testid="item.testid"
        :aria-expanded="open === item.key"
        :aria-controls="`${id}-${item.key}`"
        @click="open = open === item.key ? '' : item.key"
      ><Icon name="chevron-right" :style="{ transform: open === item.key ? 'rotate(90deg)' : undefined }" />{{ item.label }}</button>
    </div>
    <div v-for="item in items" v-show="open === item.key" :id="`${id}-${item.key}`" :key="item.key" class="stack" style="gap: 8px">
      <slot v-if="open === item.key" :name="item.key" />
    </div>
  </div>
</template>
