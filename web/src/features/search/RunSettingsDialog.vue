<script setup lang="ts">
// Read-only view of the configuration recorded when the search was submitted.
import { computed, ref } from "vue";
import type { RunDetail } from "../../api/types";
import AppDialog from "../../components/AppDialog.vue";
import Icon from "../../components/Icon.vue";
import { useLocale } from "../../locales";
import { useUi } from "../../locales/ui";

const props = defineProps<{ run: RunDetail | null; canRerun?: boolean }>();
const emit = defineEmits<{ rerun: [] }>();
const { t, sourceName, providerName } = useLocale();
const u = useUi();
const open = ref(false);
const rows = computed(() => {
  const run = props.run;
  if (!run) return [];
  const snap = run.config_snapshot || {};
  const mode = snap.retrieval?.mode || "local_fusion";
  const pre = [u(`pre_${mode}` as "pre_local_fusion")];
  if (mode === "embedding_rerank") pre.push(String(snap.retrieval?.embedding?.model || ""), String(snap.retrieval?.reranker?.model || ""));
  if (mode === "decision") pre.push(String(snap.retrieval?.decision?.model || ""));
  const fields = Array.isArray(snap.field_ids) ? snap.field_ids.length : 0;
  return [
    [u("researchQuestion"), run.question],
    [u("dataSource"), sourceName(run.source)],
    [u("searchBudget"), snap.search_budget ? t(String(snap.search_budget)) : t("notRecorded")],
    [u("fieldFilter"), fields ? String(fields) : snap.field_hint ? String(snap.field_hint) : u("fieldAll")],
    [u("searchModel"), snap.llm ? `${providerName(String(snap.llm.provider || ""))} · ${snap.llm.model || ""}` : t("notRecorded")],
    [u("preRanking"), pre.filter(Boolean).join(" · ")],
    [u("citationExpansion"), snap.citation_enabled === undefined ? t("notRecorded") : snap.citation_enabled ? "✓" : "—"],
  ];
});
</script>

<template>
  <button class="btn btn-ghost btn-sm" type="button" aria-haspopup="dialog" :disabled="!run" @click="open = true"><Icon name="sliders" />{{ u("runSettings") }}</button>
  <AppDialog v-if="open" :title="u('runSettings')" :description="u('runSettingsDesc')" @close="open = false">
    <dl class="kv" style="grid-template-columns: auto minmax(0, 1fr)">
      <template v-for="[label, value] in rows" :key="label"><dt>{{ label }}</dt><dd style="text-align: left; overflow-wrap: anywhere">{{ value }}</dd></template>
    </dl>
    <template v-if="canRerun" #footer>
      <button class="btn btn-sm" type="button" data-testid="rerun-edit" @click="open = false; emit('rerun')">{{ u("rerun") }}</button>
    </template>
  </AppDialog>
</template>
