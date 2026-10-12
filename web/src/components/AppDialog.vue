<script setup lang="ts">
// shadcn Dialog on a native <dialog>: focus trap, Esc and focus return come free.
import { onBeforeUnmount, onMounted, ref } from "vue";
import Icon from "./Icon.vue";
import { useUi } from "../locales/ui";

defineProps<{ title: string; description?: string; busy?: boolean; size?: "lg" }>();
const emit = defineEmits<{ close: [] }>();
const dialog = ref<HTMLDialogElement>();
const u = useUi();
let trigger: HTMLElement | null = null;
onMounted(() => {
  trigger = document.activeElement as HTMLElement;
  dialog.value?.showModal();
});
onBeforeUnmount(() => {
  dialog.value?.close();
  if (trigger?.isConnected) trigger.focus();
});
function backdrop(event: MouseEvent) {
  if (event.target === dialog.value) emit("close");
}
</script>

<template>
  <dialog ref="dialog" class="dlg" :class="size" :aria-label="title" @cancel.prevent="!busy && emit('close')" @click="!busy && backdrop($event)">
    <div class="dlg-body">
      <div class="dlg-head">
        <h2 class="dlg-title">{{ title }}</h2>
        <p v-if="description" class="dlg-desc">{{ description }}</p>
      </div>
      <slot />
      <div v-if="$slots.footer" class="dlg-foot"><slot name="footer" /></div>
    </div>
    <button class="btn btn-ghost btn-icon btn-xs dlg-close" type="button" :aria-label="u('close')" :disabled="busy" @click="emit('close')"><Icon name="x" /></button>
  </dialog>
</template>
