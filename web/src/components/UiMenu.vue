<script setup lang="ts">
// shadcn DropdownMenu: any trigger, `.pop` panel, `.opt` items marked data-menu-item.
import { nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";

const props = withDefaults(
  defineProps<{
    label: string;
    triggerClass?: string;
    align?: "start" | "end";
    side?: "bottom" | "right" | "top";
    minWidth?: number;
    title?: string;
    disabled?: boolean;
  }>(),
  { triggerClass: "btn btn-ghost btn-icon btn-xs", align: "start", side: "bottom", minWidth: 200 },
);
const emit = defineEmits<{ opened: [] }>();
const id = useId();
const root = ref<HTMLElement>();
const trigger = ref<HTMLButtonElement>();
const panel = ref<HTMLElement>();
const open = ref(false);
const position = ref({ left: "0px", top: "0px" });

function place() {
  const anchor = trigger.value?.getBoundingClientRect();
  if (!anchor) return;
  const width = Math.max(props.minWidth, panel.value?.offsetWidth || 0);
  const height = panel.value?.offsetHeight || 0;
  let left: number, top: number;
  if (props.side === "right") {
    left = anchor.right + 8;
    top = Math.min(anchor.top, innerHeight - height - 8);
  } else if (props.side === "top") {
    left = props.align === "end" ? anchor.right - width : anchor.left;
    top = anchor.top - height - 4;
  } else {
    left = props.align === "end" ? anchor.right - width : anchor.left;
    top = anchor.bottom + height + 8 > innerHeight ? anchor.top - height - 4 : anchor.bottom + 4;
  }
  left = Math.max(8, Math.min(innerWidth - width - 8, left));
  position.value = { left: `${left}px`, top: `${Math.max(8, top)}px` };
}
function items() {
  return Array.from(
    panel.value?.querySelectorAll<HTMLElement>('[data-menu-item]:not([aria-disabled="true"]):not(:disabled)') ?? [],
  );
}
function close(restore = false) {
  open.value = false;
  if (restore) trigger.value?.focus();
}
async function show(last = false) {
  if (props.disabled) return;
  emit("opened");
  open.value = true;
  await nextTick();
  place();
  const choices = items();
  choices[last ? choices.length - 1 : 0]?.focus();
}
function keydown(event: KeyboardEvent) {
  if (event.key === "Escape" && open.value) {
    event.preventDefault();
    close(true);
  } else if (event.key === "Tab" && open.value) {
    close();
  } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    if (!open.value) return void show(event.key === "ArrowUp" || event.key === "End");
    const choices = items();
    const index = choices.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "Home" ? 0
      : event.key === "End" ? choices.length - 1
      : (index + (event.key === "ArrowDown" ? 1 : -1) + choices.length) % choices.length;
    choices[next]?.focus();
  }
}
function outside(event: Event) {
  if (open.value && !root.value?.contains(event.target as Node)) close();
}
function clicked(event: MouseEvent) {
  const item = (event.target as Element).closest("[data-menu-item]");
  if (item && !item.hasAttribute("data-menu-keep-open")) close(true);
}
function reposition() {
  if (open.value) place();
}
watch(panel, (element, _old, cleanup) => {
  if (!element) return;
  const observer = new ResizeObserver(reposition);
  observer.observe(element);
  cleanup(() => observer.disconnect());
});
onMounted(() => {
  document.addEventListener("pointerdown", outside);
  document.addEventListener("focusin", outside);
  document.addEventListener("scroll", reposition, true);
  window.addEventListener("resize", reposition);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", outside);
  document.removeEventListener("focusin", outside);
  document.removeEventListener("scroll", reposition, true);
  window.removeEventListener("resize", reposition);
});
defineExpose({ close });
</script>

<template>
  <div ref="root" class="menu-root" @keydown="keydown">
    <button
      ref="trigger"
      type="button"
      :class="triggerClass"
      :aria-label="label"
      :title="title"
      :aria-expanded="open"
      :aria-controls="id"
      :disabled="disabled"
      aria-haspopup="menu"
      @click="open ? close() : show()"
    >
      <slot name="trigger" />
    </button>
    <div
      v-if="open"
      :id="id"
      ref="panel"
      class="pop fixed"
      role="menu"
      :aria-label="label"
      :style="{ ...position, minWidth: `${minWidth}px` }"
      @click="clicked"
    >
      <slot :close="close" />
    </div>
  </div>
</template>
