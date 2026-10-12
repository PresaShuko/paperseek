<script setup lang="ts">
import { computed, ref } from "vue";
import AppDialog from "../../components/AppDialog.vue";
import Icon from "../../components/Icon.vue";
import type { SourceFilterOptionOutput } from "../../api/generated";
import { useLocale } from "../../locales";
import { useUi } from "../../locales/ui";

const props = defineProps<{ sourceId: string; label: string; options: SourceFilterOptionOutput[]; modelValue: string[]; id?: string }>();
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();
const { filterDomainName, filterOptionName, t } = useLocale();
const u = useUi();
const open = ref(false);
const query = ref("");
const optionName = (option: SourceFilterOptionOutput) => filterOptionName(props.sourceId, option.id, option.label);
const selected = computed(() => props.options.filter((option) => props.modelValue.includes(option.id)));
const summary = computed(() => {
  if (!selected.value.length) return u("fieldAll");
  const names = selected.value.slice(0, 2).map(optionName);
  const rest = selected.value.length - names.length;
  if (rest > 0) names.push(t("fieldSummaryMore").replace("{n}", String(rest)));
  return names.join(", ");
});
const groups = computed(() => {
  const needle = query.value.trim().toLowerCase();
  const result: Array<{ domain: string; options: SourceFilterOptionOutput[] }> = [];
  for (const option of props.options) {
    if (needle && !`${optionName(option)} ${option.domain}`.toLowerCase().includes(needle)) continue;
    let group = result.find((item) => item.domain === (option.domain || ""));
    if (!group) result.push((group = { domain: option.domain || "", options: [] }));
    group.options.push(option);
  }
  return result;
});
function toggle(id: string) {
  emit("update:modelValue", props.modelValue.includes(id) ? props.modelValue.filter((value) => value !== id) : [...props.modelValue, id]);
}
function close() {
  open.value = false;
  query.value = "";
}
</script>

<template>
  <button :id="id" class="select" type="button" aria-haspopup="dialog" :aria-expanded="open" data-testid="field-selector-toggle" @click="open = true">
    <span data-testid="field-selector-summary" :class="{ ph: !selected.length }">{{ summary }}</span><Icon name="chevrons-up-down" />
  </button>
  <AppDialog v-if="open" :title="label" @close="close">
    <div class="stack" style="gap: 12px" data-testid="field-selector-panel">
      <div class="ig"><Icon name="search" /><input v-model="query" type="search" :placeholder="u('fieldSearch')" :aria-label="u('fieldSearch')" autocomplete="off" /></div>
      <div class="stack" style="gap: 12px; max-height: 50dvh; overflow-y: auto; scrollbar-gutter: stable; margin: 0 -4px; padding: 0 4px">
        <section v-for="group in groups" :key="group.domain || '_'" class="stack" style="gap: 4px">
          <p v-if="group.domain" class="opt-label" style="padding-left: 0">{{ filterDomainName(sourceId, group.domain) }}</p>
          <label v-for="option in group.options" :key="option.id" class="cb" style="padding: 4px 0">
            <input type="checkbox" :checked="modelValue.includes(option.id)" @change="toggle(option.id)" /><span class="box"><Icon name="check" /></span>{{ optionName(option) }}
          </label>
        </section>
        <p v-if="!groups.length" class="sm muted">{{ u("noMatches") }}</p>
      </div>
    </div>
    <template #footer>
      <button class="btn btn-ghost btn-sm" type="button" data-testid="field-selector-clear" :disabled="!modelValue.length" style="margin-right: auto" @click="emit('update:modelValue', [])">{{ u("clearSelection") }}</button>
      <button class="btn btn-sm" type="button" data-testid="field-selector-close" @click="close">{{ u("done") }}</button>
    </template>
  </AppDialog>
</template>
