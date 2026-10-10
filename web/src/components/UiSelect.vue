<script setup lang="ts" generic="T extends string | number">
// shadcn Select: `.select` trigger, `.pop` listbox with `.opt` rows and a check mark.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from "vue";
import Icon from "./Icon.vue";

export interface SelectOption<V> {
  value: V;
  label: string;
  desc?: string;
  hint?: string;
  status?: "ok" | "fail" | "idle";
  disabled?: boolean;
}

const props = withDefaults(
  defineProps<{
    modelValue: T;
    options: SelectOption<T>[];
    label?: string;
    prefix?: string;
    placeholder?: string;
    size?: "default" | "sm";
    inline?: boolean;
    chevron?: "up-down" | "down";
    disabled?: boolean;
    width?: string;
    id?: string;
  }>(),
  { size: "default", chevron: "up-down" },
);
const emit = defineEmits<{ "update:modelValue": [value: T] }>();
const listId = useId();
const root = ref<HTMLElement>();
const trigger = ref<HTMLButtonElement>();
const panel = ref<HTMLElement>();
const open = ref(false);
const active = ref(-1);
const position = ref<Record<string, string>>({});
const current = computed(() => props.options.find((option) => option.value === props.modelValue));

function place() {
  const anchor = trigger.value?.getBoundingClientRect();
  if (!anchor) return;
  const height = panel.value?.offsetHeight || 0;
  const width = Math.max(anchor.width, panel.value?.offsetWidth || 0);
  const below = anchor.bottom + height + 8 <= innerHeight;
  position.value = {
    left: `${Math.max(8, Math.min(innerWidth - width - 8, anchor.left))}px`,
    top: `${below ? anchor.bottom + 4 : Math.max(8, anchor.top - height - 4)}px`,
    minWidth: `${anchor.width}px`,
  };
}
function enabled(index: number) {
  return index >= 0 && index < props.options.length && !props.options[index].disabled;
}
function move(delta: number) {
  let index = active.value;
  for (let step = 0; step < props.options.length; step++) {
    index = (index + delta + props.options.length) % props.options.length;
    if (enabled(index)) break;
  }
  active.value = index;
  void nextTick(() => panel.value?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" }));
}
async function show() {
  if (props.disabled) return;
  open.value = true;
  active.value = props.options.findIndex((option) => option.value === props.modelValue);
  if (!enabled(active.value)) move(1);
  await nextTick();
  place();
  panel.value?.querySelector(`[data-index="${active.value}"]`)?.scrollIntoView({ block: "nearest" });
}
function close(restore = true) {
  open.value = false;
  if (restore) trigger.value?.focus();
}
function choose(index: number) {
  if (!enabled(index)) return;
  emit("update:modelValue", props.options[index].value);
  close();
}
function keydown(event: KeyboardEvent) {
  if (!open.value) {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      void show();
    }
    return;
  }
  if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
  else if (event.key === "Tab") close(false);
  else if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
  else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
  else if (event.key === "Home") { event.preventDefault(); active.value = -1; move(1); }
  else if (event.key === "End") { event.preventDefault(); active.value = props.options.length; move(-1); }
  else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(active.value); }
}
function outside(event: Event) {
  if (open.value && !root.value?.contains(event.target as Node)) close(false);
}
function reposition() {
  if (open.value) place();
}
onMounted(() => {
  document.addEventListener("pointerdown", outside);
  document.addEventListener("scroll", reposition, true);
  window.addEventListener("resize", reposition);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", outside);
  document.removeEventListener("scroll", reposition, true);
  window.removeEventListener("resize", reposition);
});
</script>

<template>
  <div ref="root" class="menu-root" :style="{ display: inline ? 'inline-flex' : 'flex', width: width || (inline ? undefined : '100%') }" @keydown="keydown">
    <button
      :id="id"
      ref="trigger"
      type="button"
      class="select"
      :class="{ 'select-sm': size === 'sm', inline }"
      :style="width ? { width } : undefined"
      role="combobox"
      :aria-label="label"
      :aria-expanded="open"
      :aria-controls="listId"
      aria-haspopup="listbox"
      :disabled="disabled"
      @click="open ? close() : show()"
    >
      <span v-if="current" class="row" style="gap: 8px; flex-wrap: nowrap; min-width: 0">
        <span v-if="current.status" class="sdot" :class="current.status"></span>
        <span class="truncate"><span v-if="prefix" class="muted">{{ prefix }} </span>{{ current.label }}<span v-if="current.hint" class="muted"> · {{ current.hint }}</span></span>
      </span>
      <span v-else class="ph">{{ placeholder }}</span>
      <Icon :name="chevron === 'down' ? 'chevron-down' : 'chevrons-up-down'" />
    </button>
    <div
      v-if="open"
      :id="listId"
      ref="panel"
      class="pop fixed"
      role="listbox"
      :aria-label="label"
      :style="position"
    >
      <slot name="header" />
      <div
        v-for="(option, index) in options"
        :key="String(option.value)"
        class="opt"
        :class="{ hl: index === active, tall: !!option.desc }"
        role="option"
        :data-index="index"
        :aria-selected="option.value === modelValue"
        :aria-disabled="option.disabled || undefined"
        @pointerenter="enabled(index) && (active = index)"
        @click="choose(index)"
      >
        <span v-if="option.status" class="sdot" :class="option.status" style="margin-top: 0"></span>
        <span class="opt-text grow">
          <span class="truncate">{{ option.label }}<span v-if="option.hint" class="muted"> · {{ option.hint }}</span></span>
          <span v-if="option.desc" class="opt-desc">{{ option.desc }}</span>
        </span>
        <Icon v-if="option.value === modelValue" name="check" class="check" />
      </div>
      <slot name="footer" :close="() => close(false)" />
    </div>
  </div>
</template>
