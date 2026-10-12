<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ApiError } from "../../api/client";
import Icon from "../../components/Icon.vue";
import UiSelect from "../../components/UiSelect.vue";
import UiSheet from "../../components/UiSheet.vue";
import { useLocale } from "../../locales";
import { useUi, useUiError } from "../../locales/ui";
import { decisionModelOptions, decisionProviderDefaults, providerDefaults, rerankerProviderDefaults, retrievalProviderDefaults } from "../search/provider-presets";
import { settingsApi, type Connection, type ConnectionKind, type Probe } from "./store";

const props = defineProps<{ kind: ConnectionKind; connection?: Connection }>();
const emit = defineEmits<{ close: []; saved: [connection: Connection] }>();
const { providerName } = useLocale();
const u = useUi();
const uiError = useUiError();
const kinds: Array<{ value: ConnectionKind; label: string }> = [
  { value: "llm", label: "LLM" }, { value: "embedding", label: "Embedding" }, { value: "reranker", label: "Rerank" }, { value: "decision", label: "System One" },
];
const tables: Record<ConnectionKind, Record<string, readonly string[]>> = {
  llm: providerDefaults,
  embedding: Object.fromEntries(Object.entries(retrievalProviderDefaults).filter(([key]) => key !== "local")),
  reranker: Object.fromEntries(Object.entries(rerankerProviderDefaults).filter(([key]) => key)),
  decision: decisionProviderDefaults,
};
const form = reactive({
  kind: props.connection?.kind || props.kind,
  provider: props.connection?.provider || "",
  model: props.connection?.model || "",
  base_url: props.connection?.base_url || "",
  api_type: props.connection?.api_type || "",
  api_key: "",
});
const showKey = ref(false);
const busy = ref(false);
const testing = ref(false);
const probe = ref<Probe | null>(null);
const error = ref("");
const editing = computed(() => Boolean(props.connection));

function preset(provider: string) {
  const row = tables[form.kind][provider] || [];
  return form.kind === "llm"
    ? { model: row[0] || "", api_type: row[1] || "openai_chat", base_url: row[2] || "" }
    : { model: row[0] || "", api_type: "", base_url: row[1] || "" };
}
function applyProvider(provider: string) {
  Object.assign(form, preset(provider));
}
watch(() => form.kind, (kind, previous) => {
  if (previous === undefined || editing.value) return;
  form.provider = Object.keys(tables[kind])[0];
  applyProvider(form.provider);
}, { immediate: true });
if (!form.provider) {
  form.provider = Object.keys(tables[form.kind])[0];
  applyProvider(form.provider);
}
watch(() => form.provider, (provider, previous) => {
  if (previous && provider !== previous) {
    applyProvider(provider);
    form.api_key = "";
  }
});
watch(() => [form.provider, form.model, form.base_url, form.api_type, form.api_key, form.kind], () => (probe.value = null));

const providerOptions = computed(() => Object.keys(tables[form.kind]).map((value) => ({
  value, label: value === "typesafe" ? "TypeSafe (Jev)" : providerName(value),
})));
const modelSuggestions = computed(() => {
  const values = form.kind === "decision" ? [...(decisionModelOptions[form.provider as keyof typeof decisionModelOptions] || [])] : [preset(form.provider).model];
  return [...new Set(values.flatMap((value) => value.split(",")).map((value) => value.trim()).filter(Boolean))];
});
const needsKey = computed(() => !(form.kind === "llm" && form.provider === "ollama"));
const keyMissing = computed(() => needsKey.value && !form.api_key.trim() && !(editing.value && props.connection?.has_key && sameEndpoint.value));
const sameEndpoint = computed(() => props.connection?.provider === form.provider && props.connection?.base_url.replace(/\/$/, "") === form.base_url.trim().replace(/\/$/, ""));
const host = computed(() => form.base_url.replace(/^https?:\/\//, "").split("/")[0]);
const apiTypes = [
  { value: "openai_chat", label: "OpenAI Chat Completions" },
  { value: "openai_responses", label: "OpenAI Responses" },
  { value: "anthropic_messages", label: "Anthropic Messages" },
];
const apiTypeLabel = computed(() => apiTypes.find((item) => item.value === form.api_type)?.label.replace(" Completions", "") || "");

function body() {
  return {
    kind: form.kind, provider: form.provider, model: form.model.trim(), base_url: form.base_url.trim(),
    api_type: form.kind === "llm" ? form.api_type : "",
    api_key: form.api_key.trim() || (editing.value ? null : ""),
  };
}
async function test() {
  testing.value = true;
  error.value = "";
  try {
    probe.value = await settingsApi.testDraft({ ...body(), id: props.connection?.id || "" });
  } catch (e) {
    error.value = e instanceof ApiError ? e.code : "generic";
  } finally {
    testing.value = false;
  }
}
async function save() {
  if (busy.value || keyMissing.value || !form.model.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    const saved = props.connection ? await settingsApi.update(props.connection.id, body()) : await settingsApi.create(body());
    if (probe.value && !props.connection) await settingsApi.test(saved.id).catch(() => undefined);
    emit("saved", saved);
  } catch (e) {
    error.value = e instanceof ApiError ? e.code : "generic";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiSheet :title="u(editing ? 'editConnection' : 'addConnection')" :description="u('addConnectionDesc')" :busy="busy" @close="emit('close')">
    <form id="connection-form" class="stack" style="gap: 16px" autocomplete="off" @submit.prevent="save">
      <div class="field">
        <span class="label">{{ u("kind") }}</span>
        <div class="seg" role="radiogroup" :aria-label="u('kind')" style="width: 100%; flex-wrap: nowrap">
          <label v-for="item in kinds" :key="item.value" style="flex: 1 1 0"><input v-model="form.kind" type="radio" name="connection-kind" :value="item.value" :disabled="editing" /><span style="width: 100%; padding: 0 6px">{{ item.label }}</span></label>
        </div>
      </div>
      <div class="field">
        <span class="label">{{ u("providerLabel") }}</span>
        <UiSelect v-model="form.provider" :options="providerOptions" :label="u('providerLabel')" />
      </div>
      <div class="field">
        <label class="label" for="connection-model">{{ u("model") }}</label>
        <div class="ig"><input id="connection-model" v-model="form.model" list="connection-models" required maxlength="256" aria-describedby="connection-model-help" /><Icon name="chevron-down" class="muted" style="margin-right: 12px" /></div>
        <datalist id="connection-models"><option v-for="model in modelSuggestions" :key="model" :value="model" /></datalist>
        <p id="connection-model-help" class="help">{{ u("modelHelp") }}</p>
      </div>
      <div v-if="needsKey" class="field">
        <label class="label" for="connection-key">{{ u("apiKey") }}</label>
        <div class="ig">
          <input id="connection-key" v-model="form.api_key" :type="showKey ? 'text' : 'password'" autocomplete="off" spellcheck="false" :placeholder="editing && connection?.has_key && sameEndpoint ? '••••••••' : ''" />
          <button class="btn btn-ghost btn-icon btn-xs" type="button" :aria-label="u(showKey ? 'hideKey' : 'showKey')" style="margin-right: 4px" @click="showKey = !showKey"><Icon :name="showKey ? 'eye-off' : 'eye'" /></button>
        </div>
        <p v-if="editing && connection?.has_key" class="help">{{ u("apiKeyKeep") }}</p>
      </div>
      <details style="border: 1px solid var(--border); border-radius: 10px" :open="form.provider === 'custom' || !form.base_url">
        <summary class="row" style="cursor: pointer; padding: 8px 12px; justify-content: space-between; flex-wrap: nowrap"><span class="sm medium">{{ u("advanced") }}</span><span class="xs muted row" style="gap: 4px; flex-wrap: nowrap; min-width: 0"><span class="truncate">{{ [host, form.kind === "llm" ? apiTypeLabel : ""].filter(Boolean).join(" · ") }}</span><Icon name="chevron-down" /></span></summary>
        <div class="stack" style="gap: 12px; padding: 4px 12px 12px">
          <div class="field"><label class="label" for="connection-url">{{ u("baseUrl") }}</label><input id="connection-url" v-model="form.base_url" class="input" type="url" required maxlength="2048" placeholder="https://" /></div>
          <div v-if="form.kind === 'llm'" class="field"><span class="label">{{ u("apiType") }}</span><UiSelect v-model="form.api_type" :options="apiTypes" :label="u('apiType')" /></div>
        </div>
      </details>
      <div v-if="probe" class="alert" role="status">
        <Icon :name="probe.ok ? 'ok' : 'fail'" />
        <p class="alert-title">{{ u(probe.ok ? "testOk" : "testFail") }}</p>
        <p class="alert-desc">{{ probe.ok ? u("testOkDesc", { model: form.model, ms: probe.latency_ms ?? 0 }) : uiError(probe.code || '') }}</p>
        <div class="alert-act"><button class="btn btn-ghost btn-sm" type="button" style="height: 28px" :disabled="testing" @click="test">{{ u("retest") }}</button></div>
      </div>
      <button v-else class="btn btn-outline btn-sm" type="button" style="align-self: flex-start" :disabled="testing || keyMissing || !form.model.trim()" @click="test"><Icon v-if="testing" name="loader" />{{ testing ? u("testing") : u("testConnection") }}</button>
      <p v-if="error" class="help danger-text" role="alert">{{ uiError(error) }}</p>
    </form>
    <template #footer>
      <button class="btn btn-outline btn-sm" type="button" :disabled="busy" @click="emit('close')">{{ u("cancel") }}</button>
      <button class="btn btn-sm" type="submit" form="connection-form" :disabled="busy || keyMissing || !form.model.trim()"><Icon v-if="busy" name="loader" />{{ u("save") }}</button>
    </template>
  </UiSheet>
</template>
