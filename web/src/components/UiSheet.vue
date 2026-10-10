<script setup lang="ts">
// shadcn Sheet (side="right") on a native <dialog>.
import { onBeforeUnmount, onMounted, ref } from "vue";
import Icon from "./Icon.vue";
import { useUi } from "../locales/ui";

defineProps<{ title: string; description?: string; busy?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const sheet = ref<HTMLDialogElement>();
const u = useUi();
let trigger: HTMLElement | null = null;
onMounted(() => {
  trigger = document.activeElement as HTMLElement;
  sheet.value?.showModal();
  sheet.value?.querySelector<HTMLElement>("input:not([type=radio]):not([disabled]), textarea")?.focus();
});
onBeforeUnmount(() => {
  sheet.value?.close();
  if (trigger?.isConnected) trigger.focus();
});
function backdrop(event: MouseEvent) {
  if (event.target === sheet.value) emit("close");
}
</script>

<template>
  <dialog ref="sheet" class="sheet" :aria-label="title" @cancel.prevent="!busy && emit('close')" @click="!busy && backdrop($event)">
    <div class="sheet-head">
      <h2 class="card-title">{{ title }}</h2>
      <p v-if="description" class="help">{{ description }}</p>
      <button class="btn btn-ghost btn-icon btn-xs" type="button" :aria-label="u('close')" :disabled="busy" style="position: absolute; top: 12px; right: 12px" @click="emit('close')"><Icon name="x" /></button>
    </div>
    <div class="sheet-body"><slot /></div>
    <div v-if="$slots.footer" class="sheet-foot"><slot name="footer" /></div>
  </dialog>
</template>
