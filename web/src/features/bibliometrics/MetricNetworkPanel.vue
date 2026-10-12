<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { ApiError } from "../../api/client";
import Icon from "../../components/Icon.vue";
import UiSelect from "../../components/UiSelect.vue";
import { useUi } from "../../locales/ui";
import { metricsApi, type MetricNetwork } from "./api";
import { useMetricMessages } from "./messages";
import MetricNetworkView from "./MetricNetworkView.vue";

const props = defineProps<{ analysisId: string; sourceRunId: string; kind: "keywords" | "coupling" }>();
const { m } = useMetricMessages();
const u = useUi();
const form = reactive({ min_occurrences: props.kind === "keywords" ? 3 : 2, min_weight: props.kind === "keywords" ? 2 : 1, max_nodes: 100, max_reference_frequency: "" });
const result = ref<MetricNetwork | null>(null);
const busy = ref(false);
const error = ref("");
const nodeOptions = [50, 100, 200, 300].map((value) => ({ value, label: String(value) }));
const reference = () => (props.kind === "coupling" && form.max_reference_frequency ? Number(form.max_reference_frequency) : null);
const pending = computed(() => result.value && (
  result.value.parameters.min_occurrences !== form.min_occurrences || result.value.parameters.min_weight !== form.min_weight
  || result.value.parameters.max_nodes !== form.max_nodes || (result.value.parameters.max_reference_frequency ?? null) !== reference()));
let controller: AbortController | undefined;
let generation = 0;
watch(() => props.analysisId, () => {
  generation++;
  controller?.abort();
  result.value = null;
  error.value = "";
  busy.value = false;
});
onBeforeUnmount(() => {
  generation++;
  controller?.abort();
});
async function generate() {
  const own = ++generation;
  controller?.abort();
  controller = new AbortController();
  busy.value = true;
  error.value = "";
  try {
    const value = await metricsApi.network(props.analysisId, {
      kind: props.kind, min_occurrences: form.min_occurrences, min_weight: form.min_weight, max_nodes: form.max_nodes,
      max_edges: 500, max_reference_frequency: reference(),
    }, controller.signal);
    if (own === generation) result.value = value;
  } catch (e) {
    if (own === generation && !controller.signal.aborted) error.value = e instanceof ApiError && m(e.code) !== e.code ? e.code : "error";
  } finally {
    if (own === generation) busy.value = false;
  }
}
</script>

<template>
  <form class="row" style="gap: 12px; align-items: flex-end; padding: 12px 16px; border: 1px solid var(--border); border-radius: 10px" :aria-label="m('parameters')" @submit.prevent="generate">
    <div class="field" style="flex: 1 1 150px; gap: 6px">
      <label class="label" :for="`${kind}-min`" style="font-size: 12px">{{ m("minimum") }}{{ m(kind === "keywords" ? "keywordOccurrences" : "referenceCount") }}</label>
      <input :id="`${kind}-min`" v-model.number="form.min_occurrences" class="input input-sm" type="number" min="1" max="10000" required />
    </div>
    <div class="field" style="flex: 1 1 150px; gap: 6px">
      <label class="label" :for="`${kind}-weight`" style="font-size: 12px">{{ m("minimum") }}{{ m(kind === "keywords" ? "cooccurrences" : "sharedReferences") }}</label>
      <input :id="`${kind}-weight`" v-model.number="form.min_weight" class="input input-sm" type="number" min="1" max="10000" required />
    </div>
    <div v-if="kind === 'coupling'" class="field" style="flex: 1 1 150px; gap: 6px">
      <label class="label" :for="`${kind}-ref`" style="font-size: 12px">{{ m("maxReference") }}</label>
      <input :id="`${kind}-ref`" v-model="form.max_reference_frequency" class="input input-sm" type="number" min="2" max="10000" :placeholder="m('noFilter')" />
    </div>
    <div class="field" style="flex: 1 1 130px; gap: 6px">
      <span class="label" style="font-size: 12px">{{ m("maxNodes") }}</span>
      <UiSelect v-model="form.max_nodes" :options="nodeOptions" :label="m('maxNodes')" size="sm" />
    </div>
    <button class="btn btn-sm" type="submit" :disabled="busy"><Icon v-if="busy" name="loader" />{{ m(busy ? "generating" : "generate") }}</button>
    <button class="btn btn-ghost btn-icon btn-sm" type="button" :aria-label="u('explain')" :title="m(kind === 'keywords' ? 'topicHint' : 'couplingHint')"><Icon name="info" /></button>
  </form>
  <div v-if="error" class="alert" role="alert" style="grid-template-columns: 16px 1fr"><Icon name="fail" /><p class="alert-title">{{ m(error) }}</p></div>
  <div v-if="pending" class="alert" role="status" style="grid-template-columns: 16px 1fr"><Icon name="info" /><p class="alert-title">{{ m("parametersPending") }}</p></div>
  <MetricNetworkView v-if="result && result.nodes.length && result.edges.length" :network="result" :source-run-id="sourceRunId" />
  <div v-else class="empty">
    <span class="empty-media"><Icon :name="busy ? 'loader' : 'chart'" size="lg" /></span>
    <p class="empty-title">{{ m(result ? "networkEmpty" : "networkIdle") }}</p>
    <p class="empty-desc">{{ m(result ? "networkEmptyHint" : "networkIdleHint") }}</p>
  </div>
</template>
