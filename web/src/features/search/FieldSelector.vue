<script setup lang="ts">
import { computed, ref } from "vue";

import type { SourceFilterOptionOutput } from "../../api/generated";
import { useLocale } from "../../locales";

const props = defineProps<{
  sourceId: string;
  label: string;
  options: SourceFilterOptionOutput[];
  modelValue: string[];
}>();
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();

const { filterDomainName, filterOptionName, t } = useLocale();
const open = ref(false);
const query = ref("");
const toggleButton = ref<HTMLButtonElement | null>(null);

function optionName(option: SourceFilterOptionOutput): string {
  return filterOptionName(props.sourceId, option.id, option.label);
}

function domainName(domain: string): string {
  return filterDomainName(props.sourceId, domain);
}

const selectedOptions = computed(() => props.options.filter((option) => props.modelValue.includes(option.id)));

// Collapsed summary: the active restriction must always be visible (§4.3).
const summary = computed(() => {
  if (!selectedOptions.value.length) return t("fieldUnrestricted");
  const names = selectedOptions.value.slice(0, 2).map((option) => optionName(option));
  const rest = selectedOptions.value.length - names.length;
  if (rest > 0) names.push(t("fieldSummaryMore").replace("{n}", String(rest)));
  return names.join(t("fieldSummaryJoin"));
});

const grouped = computed(() => {
  const needle = query.value.trim().toLowerCase();
  const matched = needle
    ? props.options.filter((option) => `${optionName(option)} ${option.domain}`.toLowerCase().includes(needle))
    : props.options;
  const groups: Array<{ domain: string; options: SourceFilterOptionOutput[] }> = [];
  for (const option of matched) {
    const domain = option.domain || "";
    let group = groups.find((item) => item.domain === domain);
    if (!group) {
      group = { domain, options: [] };
      groups.push(group);
    }
    group.options.push(option);
  }
  return groups;
});

function toggleOption(id: string): void {
  const next = props.modelValue.includes(id)
    ? props.modelValue.filter((value) => value !== id)
    : [...props.modelValue, id];
  emit("update:modelValue", next);
}

function clearSelection(): void {
  emit("update:modelValue", []);
}

// Closing never clears the selection; focus returns to the trigger (§4.3).
function close(): void {
  open.value = false;
  query.value = "";
  toggleButton.value?.focus();
}

function onPanelKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
  }
}
</script>

<template>
  <fieldset class="filter-group field-selector" data-testid="source-filter">
    <legend>{{ label }}</legend>
    <button
      ref="toggleButton"
      type="button"
      class="field-selector-summary"
      data-testid="field-selector-toggle"
      :aria-expanded="open"
      aria-haspopup="true"
      @click="open ? close() : (open = true)"
    >
      <span class="field-selector-value" data-testid="field-selector-summary">{{ summary }}</span>
      <svg class="disclosure-icon" :class="{ 'disclosure-icon--open': open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
    </button>
    <div v-if="open" class="field-selector-panel" data-testid="field-selector-panel" @keydown="onPanelKeydown">
      <input
        v-model="query"
        type="search"
        class="field-selector-search"
        data-testid="field-selector-search"
        :placeholder="t('fieldSelectorSearch')"
        :aria-label="t('fieldSelectorSearch')"
        autocomplete="off"
      />
      <div class="field-selector-groups">
        <div v-for="group in grouped" :key="group.domain || '_'" class="field-selector-group">
          <div v-if="group.domain" class="field-selector-domain">{{ domainName(group.domain) }}</div>
          <label v-for="option in group.options" :key="option.id" class="toggle-field">
            <input
              type="checkbox"
              :checked="modelValue.includes(option.id)"
              :aria-label="optionName(option)"
              @change="toggleOption(option.id)"
            />
            <span>
              <strong>{{ optionName(option) }}</strong>
              <small v-if="option.domain">{{ domainName(option.domain) }}</small>
            </span>
          </label>
        </div>
        <p v-if="!grouped.length" class="field-help">{{ t("noFilteredResults") }}</p>
      </div>
      <div class="field-selector-actions">
        <button type="button" class="button button--small" data-testid="field-selector-clear" :disabled="!modelValue.length" @click="clearSelection">{{ t("clearSelection") }}</button>
        <button type="button" class="button button--small" data-testid="field-selector-close" @click="close">{{ t("done") }}</button>
      </div>
    </div>
  </fieldset>
</template>
