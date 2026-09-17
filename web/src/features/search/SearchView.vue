<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api, ApiError } from "../../api/client";
import type { DiagnosticCheck, DiagnosticResult, DiagnosticSubmission, RunDetail, SearchSubmission, SourceDescriptor } from "../../api/types";
import { useLocale } from "../../locales";
import { submitSearch } from "../../state/run";
import WorkflowStages from "./WorkflowStages.vue";

const QUESTION_MAX_LENGTH = 10_000; // Backend contract: RunSubmission.question max_length.
const props = withDefaults(defineProps<{
  submissionEnabled?: boolean;
  service?: DiagnosticSubmission['service'];
  modelSettings?: Pick<DiagnosticSubmission, 'llm' | 'retrieval'>;
  sourceOptions?: SourceDescriptor[];
  credentialHelp?: string;
}>(), { submissionEnabled: true });
const emit = defineEmits<{ submitted: [run: RunDetail] }>();

const { filterDomainName, filterOptionName, providerName, sourceName, t } = useLocale();
const router = useRouter();
const sources = ref<SourceDescriptor[]>([]);
const sourceError = ref("");
const busy = ref(false);
const submitError = ref("");
const activeConflict = ref<RunDetail | null>(null);
const stopConflictBusy = ref(false);
const diagnosticsBusy = ref(false);
const diagnosticResult = ref<DiagnosticResult | null>(null);
const diagnosticError = ref("");
const providerDefaults = {
  openai: ["gpt-5.4-mini", "openai_responses", "https://api.openai.com/v1"],
  anthropic: ["claude-sonnet-4-6", "anthropic_messages", "https://api.anthropic.com"],
  google: ["gemini-3.5-flash", "openai_chat", "https://generativelanguage.googleapis.com/v1beta/openai"],
  deepseek: ["deepseek-v4-flash", "openai_chat", "https://api.deepseek.com"],
  cstcloud: ["deepseek-v4-flash", "openai_chat", "https://uni-api.cstcloud.cn/v1"],
  dashscope: ["qwen3.6-plus", "openai_chat", "https://dashscope.aliyuncs.com/compatible-mode/v1"],
  moonshot: ["kimi-k2.6", "openai_chat", "https://api.moonshot.cn/v1"],
  zhipu: ["glm-5.1", "openai_chat", "https://open.bigmodel.cn/api/paas/v4"],
  siliconflow: ["deepseek-ai/DeepSeek-V4-Flash", "openai_chat", "https://api.siliconflow.cn/v1"],
  openrouter: ["openai/gpt-5.4-mini", "openai_chat", "https://openrouter.ai/api/v1"],
  nvidia: ["nvidia/llama-3.3-nemotron-super-49b-v1.5", "openai_chat", "https://integrate.api.nvidia.com/v1"],
  volcengine: ["doubao-seed-2-0-mini-260428", "openai_chat", "https://ark.cn-beijing.volces.com/api/v3"],
  hunyuan: ["hunyuan-turbos-latest", "openai_chat", "https://tokenhub.tencentmaas.com/v1"],
  qianfan: ["ernie-5.0", "openai_chat", "https://qianfan.baidubce.com/v2"],
  modelscope: ["Qwen/Qwen3-235B-A22B-Instruct-2507", "openai_chat", "https://api-inference.modelscope.cn/v1"],
  ollama: ["qwen3:8b", "openai_chat", "http://127.0.0.1:11434/v1"],
  custom: ["", "openai_chat", ""],
} as const;
const retrievalProviderDefaults = {
  local: ["", ""],
  cstcloud: ["qwen3-embedding:8b,bge-large-zh:latest", "https://uni-api.cstcloud.cn/v1"],
  openai: ["text-embedding-3-large", "https://api.openai.com/v1"],
  dashscope: ["text-embedding-v4", "https://dashscope.aliyuncs.com/compatible-mode/v1"],
  siliconflow: ["BAAI/bge-large-zh-v1.5", "https://api.siliconflow.cn/v1"],
  openrouter: ["openai/text-embedding-3-small", "https://openrouter.ai/api/v1"],
  nvidia: ["nvidia/nv-embedqa-e5-v5", "https://integrate.api.nvidia.com/v1"],
  zhipu: ["embedding-3", "https://open.bigmodel.cn/api/paas/v4"],
  volcengine: ["", "https://ark.cn-beijing.volces.com/api/v3"],
  modelscope: ["Qwen/Qwen3-Embedding-8B,Qwen/Qwen3-Embedding-4B", "https://api-inference.modelscope.cn/v1"],
  custom: ["", ""],
} as const;
const rerankerProviderDefaults = {
  "": ["", ""],
  cstcloud: ["qwen3-reranker:8b", "https://uni-api.cstcloud.cn/v1"],
  openrouter: ["jinaai/jina-reranker-v2-base-multilingual", "https://openrouter.ai/api/v1"],
  nvidia: ["nv-rerank-qa-mistral-4b:1", "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"],
  siliconflow: ["BAAI/bge-reranker-v2-m3", "https://api.siliconflow.cn/v1"],
  custom: ["", ""],
} as const;
const form = reactive({
  question: "",
  source: "openalex",
  searchBudget: "fast" as SearchSubmission["search_budget"],
  fieldIds: [] as string[],
  fieldHint: "",
  citationEnabled: true,
  llmProvider: "openai" as keyof typeof providerDefaults,
  llmApiType: "openai_responses",
  llmBaseUrl: "https://api.openai.com/v1",
  llmModel: "gpt-5.4-mini",
  llmApiKey: "",
  sourceApiKey: "",
  embeddingProvider: "local" as keyof typeof retrievalProviderDefaults,
  embeddingModel: "",
  embeddingBaseUrl: "",
  embeddingApiKey: "",
  rerankerProvider: "" as keyof typeof rerankerProviderDefaults,
  rerankerModel: "",
  rerankerBaseUrl: "",
  rerankerApiKey: "",
});

const selectedSource = computed(() => sources.value.find((source) => source.id === form.source));
const selectedFilter = computed(() => selectedSource.value?.capabilities.filter);
const selectedFilterLabel = computed(() => {
  const source = selectedSource.value;
  if (!source) return t("fieldHint");
  if (source.id === "openalex") return t("openAlexField");
  if (source.id === "wos") return t("webOfScienceCategory");
  if (source.id === "arxiv") return t("arxivCategory");
  return `${sourceName(source.id, source.label)} · ${t("fieldHint")}`;
});
const sourceCredentialLabel = computed(() => {
  const source = selectedSource.value;
  if (!source) return t("localizedApiKey");
  const key = `credentialLabel_${source.id}`;
  const localized = t(key);
  return localized === key ? `${source.label} ${t("localizedApiKey")}` : localized;
});
const sourceCredentialGuidance = computed(() => {
  const source = selectedSource.value;
  if (!source) return t("credentialGuidance");
  const key = `credentialGuidance_${source.id}`;
  const localized = t(key);
  return localized === key ? `${t("getCredential")} ${source.label} ${t("credentialKey")}` : localized;
});
const sourceCredentialRequirement = computed(() => t(`credential_${selectedSource.value?.api_key || "not_required"}`));
const supportsCitationExpansion = computed(
  () => Boolean(selectedSource.value?.capabilities.citation_expansion),
);
const budgetHintKey = computed(() => (({
  fast: "budgetHintFast",
  medium: "budgetHintMedium",
  high: "budgetHintHigh",
  max: "budgetHintMax",
}) as Record<string, string>)[form.searchBudget || "fast"]);
const canSubmit = computed(() => props.submissionEnabled && Boolean(form.question.trim()) && !busy.value);

watch(() => form.llmProvider, (provider) => {
  const [model, apiType, baseUrl] = providerDefaults[provider];
  form.llmModel = model;
  form.llmApiType = apiType;
  form.llmBaseUrl = baseUrl;
});
watch(() => form.embeddingProvider, (provider) => {
  [form.embeddingModel, form.embeddingBaseUrl] = retrievalProviderDefaults[provider];
});
watch(() => form.rerankerProvider, (provider) => {
  [form.rerankerModel, form.rerankerBaseUrl] = rerankerProviderDefaults[provider];
});

watch(() => form.source, () => {
  form.fieldIds = [];
  form.fieldHint = "";
  form.sourceApiKey = "";
  form.citationEnabled = supportsCitationExpansion.value;
});

onMounted(async () => {
  await loadSources();
});

watch(() => props.sourceOptions, value => { if (value) applySources(value); });
watch(() => props.service?.mode, clearCredentials);

function applySources(value: SourceDescriptor[]): void {
  sources.value = value;
  if (!value.some(source => source.id === form.source)) {
    const preferred = value.find(source => source.default) || value[0];
    if (preferred) form.source = preferred.id;
  }
}

async function loadSources(): Promise<void> {
  sourceError.value = "";
  try {
    if (props.sourceOptions) { applySources(props.sourceOptions); return; }
    sources.value = await api.sources();
    const preferred = sources.value.find((source) => source.default) || sources.value[0];
    if (preferred) form.source = preferred.id;
    form.citationEnabled = supportsCitationExpansion.value;
  } catch (error) {
    sourceError.value = error instanceof Error ? error.message : "sources_unavailable";
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  busy.value = true;
  submitError.value = "";
  activeConflict.value = null;
  try {
    const run = await submitSearch({ question: form.question, ...configurationPayload() });
    clearCredentials();
    emit('submitted', run);
    await router.push(`/runs/${run.id}`);
  } catch (error) {
    if (error instanceof ApiError && error.code === "active_run_exists") {
      activeConflict.value = await findActiveRun();
      if (!activeConflict.value) submitError.value = error.code;
    } else {
      submitError.value = error instanceof Error ? error.message : "run_unavailable";
    }
  } finally {
    busy.value = false;
  }
}

async function findActiveRun(): Promise<RunDetail | null> {
  try {
    const page = await api.history();
    return page.items.find((item) => ["queued", "running", "cancelling"].includes(item.status)) || null;
  } catch {
    return null;
  }
}

async function stopActiveConflict(): Promise<void> {
  const run = activeConflict.value;
  if (!run || stopConflictBusy.value) return;
  stopConflictBusy.value = true;
  try {
    await api.cancel(run.id);
    activeConflict.value = null;
  } catch (error) {
    submitError.value = error instanceof Error ? error.message : "cancel_unavailable";
  } finally {
    stopConflictBusy.value = false;
  }
}

// Ctrl/Cmd+Enter is equivalent to the primary action (§5.1).
function onSubmitShortcut(event: KeyboardEvent): void {
  if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter") return;
  if (event.isComposing) return;
  if (busy.value || diagnosticsBusy.value || !form.question.trim()) return;
  event.preventDefault();
  void submit();
}

function configurationPayload(): DiagnosticSubmission {
  return {
      source: form.source,
      search_budget: form.searchBudget,
      field_ids: selectedFilter.value?.mode === "native" ? form.fieldIds : [],
      field_hint: selectedFilter.value?.mode === "text" ? form.fieldHint : "",
      citation_enabled: supportsCitationExpansion.value && form.citationEnabled,
      service: props.service,
      llm: props.modelSettings?.llm ?? {
        provider: form.llmProvider,
        api_type: form.llmApiType,
        base_url: form.llmBaseUrl,
        model: form.llmModel,
      },
      retrieval: props.modelSettings?.retrieval ?? {
        embedding: {
          provider: form.embeddingProvider,
          model: form.embeddingModel,
          base_url: form.embeddingBaseUrl,
        },
        reranker: {
          provider: form.rerankerProvider,
          model: form.rerankerModel,
          base_url: form.rerankerBaseUrl,
        },
      },
      credentials: {
        llm: { api_key: props.modelSettings ? '' : form.llmApiKey },
        source: { api_key: form.sourceApiKey },
        embedding: { api_key: props.modelSettings ? '' : form.embeddingApiKey },
        reranker: { api_key: props.modelSettings ? '' : form.rerankerApiKey },
      },
  };
}

function clearCredentials(): void {
  form.llmApiKey = "";
  form.sourceApiKey = "";
  form.embeddingApiKey = "";
  form.rerankerApiKey = "";
}

defineExpose({ clearCredentials });

async function checkConfiguration(): Promise<void> {
  if (!props.submissionEnabled) return;
  diagnosticsBusy.value = true;
  diagnosticError.value = "";
  diagnosticResult.value = null;
  try {
    diagnosticResult.value = await api.diagnostics(configurationPayload());
  } catch (error) {
    diagnosticError.value = error instanceof Error ? error.message : "diagnostics_unavailable";
  } finally {
    diagnosticsBusy.value = false;
  }
}

function diagnosticSummary(check: DiagnosticCheck): string {
  const passed = check.status === "pass";
  const failed = check.status === "fail";
  if (check.id === "source.supported") {
    return `${sourceName(form.source, selectedSource.value?.label)} ${t(passed ? "diagnosticSourceSupported" : "diagnosticSourceUnsupported")}`;
  }
  if (check.id === "source.credentials") {
    return t(failed
      ? "diagnosticSourceCredentialRequired"
      : check.status === "warning"
        ? "diagnosticSourceCredentialMissing"
        : "diagnosticSourceCredentialSatisfied");
  }
  if (check.id === "source.status") {
    return `${sourceName(form.source, selectedSource.value?.label)} ${t("diagnosticSourceUnavailable")}`;
  }
  if (check.id === "llm.provider") {
    return `${providerName(form.llmProvider)} ${t(passed ? "diagnosticProviderSupported" : "diagnosticProviderUnsupported")}`;
  }
  if (check.id === "llm.api_type") return t(passed ? "diagnosticApiTypeSupported" : "diagnosticApiTypeUnsupported");
  if (check.id === "llm.api_key") return t(passed ? "diagnosticLlmCredentialSatisfied" : "diagnosticLlmCredentialRequired");
  if (check.id === "llm.base_url") return t(`diagnosticBaseUrl${check.status === "pass" ? "Pass" : check.status === "warning" ? "Warning" : "Fail"}`);
  if (check.id.startsWith("retrieval.")) return t(`diagnosticRetrieval${check.status === "pass" ? "Pass" : check.status === "warning" ? "Warning" : "Fail"}`);
  return t(`diagnosticCheck${check.status === "pass" ? "Pass" : check.status === "warning" ? "Warning" : "Fail"}`);
}

function diagnosticActions(check: DiagnosticCheck): string[] {
  if (!check.actions.length) return [];
  if (check.id === "source.supported" || check.id === "source.status") return [t("actionChooseSource")];
  if (check.id === "source.credentials") return [t("actionConfigureSourceCredential")];
  if (check.id === "llm.provider") return [t("actionChooseProvider")];
  if (check.id === "llm.api_type") return [t("actionChooseApiType")];
  if (check.id === "llm.api_key") return [t("actionConfigureLlmCredential")];
  if (check.id === "llm.base_url") return [t("actionCorrectEndpoint")];
  if (check.id.startsWith("retrieval.")) return [t("actionCompleteRetrieval")];
  return [];
}
</script>

<template>
  <div class="workbench">
    <div class="workbench-pane workbench-pane--config">
      <form class="search-form" autocomplete="off" novalidate @submit.prevent="submit" @keydown="onSubmitShortcut">
        <section class="form-section form-section--flat" :aria-label="t('searchControls')">
          <div class="field">
            <label class="field-label" for="research-question">{{ t("researchQuestion") }}</label>
            <textarea
              id="research-question"
              v-model="form.question"
              rows="4"
              required
              :maxlength="QUESTION_MAX_LENGTH"
              :placeholder="t('questionPlaceholder')"
            ></textarea>
            <span class="question-count">{{ form.question.length }} / {{ QUESTION_MAX_LENGTH }} {{ t("questionCountLabel") }}</span>
          </div>
          <label class="field">
            <span class="field-label">{{ t("dataSource") }}</span>
            <select v-model="form.source">
              <option v-for="source in sources" :key="source.id" :value="source.id">{{ sourceName(source.id, source.label) }}</option>
            </select>
          </label>
          <slot name="source-note" :source="selectedSource" />
          <div v-if="sourceError" class="alert" role="alert">
            <strong>{{ t("sources_unavailable") }}</strong>
            <div class="alert-actions">
              <button class="button button--small" type="button" @click="loadSources">{{ t("retry") }}</button>
            </div>
          </div>
          <fieldset class="filter-group">
            <legend>{{ t("searchBudget") }}</legend>
            <div class="segmented budget-segmented">
              <label v-for="budget in ['fast', 'medium', 'high', 'max']" :key="budget">
                <input v-model="form.searchBudget" type="radio" name="searchBudget" :value="budget" />
                <span>{{ t(budget) }}</span>
              </label>
            </div>
            <p class="budget-hint">{{ t(budgetHintKey) }}</p>
          </fieldset>
          <fieldset
            v-if="selectedFilter?.mode === 'native'"
            class="filter-group"
            data-testid="source-filter"
          >
            <legend>{{ selectedFilterLabel }}</legend>
            <div class="filter-options">
              <label v-for="option in selectedFilter.options" :key="option.id" class="toggle-field">
                <input
                  v-model="form.fieldIds"
                  type="checkbox"
                  :value="option.id"
                  :aria-label="filterOptionName(form.source, option.id, option.label)"
                />
                <span>
                  <strong>{{ filterOptionName(form.source, option.id, option.label) }}</strong>
                  <small>{{ filterDomainName(form.source, option.domain) }}</small>
                </span>
              </label>
            </div>
          </fieldset>
          <label
            v-else-if="selectedFilter?.mode === 'text'"
            class="field"
            data-testid="source-filter"
          >
            <span class="field-label">{{ selectedFilterLabel }}</span>
            <input v-model="form.fieldHint" type="text" autocomplete="off" />
          </label>
          <label v-if="supportsCitationExpansion" class="toggle-field">
            <input v-model="form.citationEnabled" type="checkbox" />
            <span><strong>{{ t("expandCitations") }}</strong><small>{{ t("citationHelp") }}</small></span>
          </label>
          <div
            v-if="selectedSource?.credential"
            class="field"
            data-testid="source-credential"
          >
            <label class="field">
              <span class="field-label">{{ sourceCredentialLabel }}</span>
              <input v-model="form.sourceApiKey" type="password" autocomplete="off" />
            </label>
            <span class="credential-note">
              <span data-testid="source-credential-requirement">{{ sourceCredentialRequirement }}</span>
              <a
                :href="selectedSource.credential.guidance_url"
                target="_blank"
                rel="noreferrer"
              >{{ sourceCredentialGuidance }}</a>
            </span>
          </div>
        </section>

        <slot name="service-mode" />
        <section class="form-section" :aria-label="t('modelConfiguration')">
          <div v-show="!modelSettings" style="display: contents">
          <div>
            <div class="section-kicker">{{ t("configuration") }}</div>
            <h2 class="section-title">{{ t("modelSource") }}</h2>
          </div>
          <div class="field-grid">
            <label class="field span-2"><span class="field-label">{{ t("provider") }}</span>
              <select v-model="form.llmProvider">
                <option v-for="provider in Object.keys(providerDefaults)" :key="provider" :value="provider">{{ providerName(provider) }}</option>
              </select>
            </label>
            <label class="field"><span class="field-label">{{ t("model") }}</span><input v-model="form.llmModel" type="text" /></label>
            <div class="field">
              <label class="field">
                <span class="field-label">{{ t("apiKey") }}</span>
                <input v-model="form.llmApiKey" type="password" autocomplete="off" />
              </label>
              <span class="field-help">{{ credentialHelp || t("credentialHelp") }}</span>
            </div>
          </div>
          </div>
          <div class="alert-actions">
            <button class="button" type="button" :disabled="!submissionEnabled || busy || diagnosticsBusy" @click="checkConfiguration">
              {{ diagnosticsBusy ? t("checkingConfiguration") : t("checkConfiguration") }}
            </button>
          </div>
          <div v-if="diagnosticResult" class="diagnostics-result" data-testid="diagnostic-result" aria-live="polite">
            <span class="badge" :class="diagnosticResult.status === 'pass' ? 'badge--success' : diagnosticResult.status === 'warning' ? 'badge--accent' : 'badge--danger'" data-testid="diagnostic-status">{{ t(diagnosticResult.status) }}</span>
            <ul class="diagnostics-list">
              <li v-for="check in diagnosticResult.checks" :key="check.id" class="diagnostics-item">
                <span class="badge" :class="check.status === 'pass' ? 'badge--success' : check.status === 'warning' ? 'badge--accent' : 'badge--danger'">{{ t(check.status) }}</span>
                <div>
                  <span>{{ diagnosticSummary(check) }}</span>
                  <ul v-if="diagnosticActions(check).length" class="diagnostics-actions">
                    <li v-for="action in diagnosticActions(check)" :key="action">{{ action }}</li>
                  </ul>
                </div>
              </li>
            </ul>
          </div>
          <div v-if="diagnosticError" class="alert" role="alert">
            <strong>{{ t("diagnostics_unavailable") }}</strong>
          </div>
        </section>

        <div class="form-actions">
          <button class="button button--primary" type="submit" :disabled="!canSubmit">
            <span>{{ busy ? t("submitting") : t("runSearch") }}</span>
          </button>
          <div v-if="activeConflict" class="alert" role="alert">
            <strong>{{ t("activeRunExists") }}</strong>
            <span>{{ t("activeRunExistsDetail") }}</span>
            <div class="alert-actions">
              <RouterLink class="button button--small" :to="`/runs/${activeConflict.id}`">{{ t("viewCurrentRun") }}</RouterLink>
              <button class="button button--small button--danger" type="button" :disabled="stopConflictBusy" @click="stopActiveConflict">
                {{ stopConflictBusy ? t("stopping") : t("stopCurrentRun") }}
              </button>
            </div>
          </div>
          <div v-else-if="submitError" class="alert" role="alert">
            <slot name="submit-error" :code="submitError"><strong>{{ t(submitError) }}</strong></slot>
          </div>
        </div>

        <details v-show="!modelSettings" class="advanced-section">
          <summary>
            <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
            <span>{{ t("advanced") }}</span>
          </summary>
          <div class="advanced-body">
            <div class="field-grid">
              <label class="field"><span class="field-label">{{ t("apiType") }}</span>
                <select v-model="form.llmApiType">
                  <option value="openai_chat">OpenAI Chat Completions</option>
                  <option value="openai_responses">OpenAI Responses</option>
                  <option value="anthropic_messages">Anthropic Messages</option>
                </select>
              </label>
              <label class="field"><span class="field-label">{{ t("baseUrl") }}</span><input v-model="form.llmBaseUrl" type="url" /></label>
            </div>
            <div class="field-grid">
              <label class="field"><span class="field-label">{{ t("embeddingProvider") }}</span>
                <select v-model="form.embeddingProvider">
                  <option v-for="provider in Object.keys(retrievalProviderDefaults)" :key="provider" :value="provider">{{ providerName(provider) }}</option>
                </select>
              </label>
              <label class="field"><span class="field-label">{{ t("embeddingModel") }}</span><input v-model="form.embeddingModel" type="text" /></label>
              <label class="field"><span class="field-label">{{ t("embeddingBaseUrl") }}</span><input v-model="form.embeddingBaseUrl" type="url" /></label>
              <div class="field">
                <label class="field">
                  <span class="field-label">{{ t("embeddingApiKey") }}</span>
                  <input v-model="form.embeddingApiKey" type="password" autocomplete="off" />
                </label>
                <span class="field-help">{{ credentialHelp || t("credentialHelp") }}</span>
              </div>
              <label class="field"><span class="field-label">{{ t("rerankerProvider") }}</span>
                <select v-model="form.rerankerProvider">
                  <option value="">{{ t("off") }}</option>
                  <option v-for="provider in Object.keys(rerankerProviderDefaults).filter((value) => value)" :key="provider" :value="provider">{{ providerName(provider) }}</option>
                </select>
              </label>
              <label class="field"><span class="field-label">{{ t("rerankerModel") }}</span><input v-model="form.rerankerModel" type="text" /></label>
              <label class="field"><span class="field-label">{{ t("rerankerBaseUrl") }}</span><input v-model="form.rerankerBaseUrl" type="url" /></label>
              <div class="field">
                <label class="field">
                  <span class="field-label">{{ t("rerankerApiKey") }}</span>
                  <input v-model="form.rerankerApiKey" type="password" autocomplete="off" />
                </label>
                <span class="field-help">{{ credentialHelp || t("credentialHelp") }}</span>
              </div>
            </div>
          </div>
        </details>
      </form>
    </div>
    <div class="workbench-pane workbench-pane--audit">
      <WorkflowStages>
        <template v-if="$slots['log-export']" #log-export="scope"><slot name="log-export" v-bind="scope" /></template>
      </WorkflowStages>
    </div>
  </div>
</template>
