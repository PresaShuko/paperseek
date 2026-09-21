<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, ApiError } from "../../api/client";
import type { DiagnosticResult, DiagnosticSubmission, RunDetail, SearchSubmission, SourceDescriptor } from "../../api/types";
import { useLocale } from "../../locales";
import { cancelRun, recoverRun, runState, stopRunRecovery, submitSearch, type StageKey } from "../../state/run";
import { diagnosticActions, diagnosticSummary } from "./diagnostic-text";
import FieldSelector from "./FieldSelector.vue";
import { providerDefaults, rerankerProviderDefaults, retrievalProviderDefaults } from "./provider-presets";
import WorkflowStages from "./WorkflowStages.vue";

const QUESTION_MAX_LENGTH = 10_000; // Backend contract: RunSubmission.question max_length.
const props = withDefaults(defineProps<{
  mode: "edit" | "run";
  submissionEnabled?: boolean;
  service?: DiagnosticSubmission['service'];
  modelSettings?: Pick<DiagnosticSubmission, 'llm' | 'retrieval'>;
  sourceOptions?: SourceDescriptor[];
  credentialHelp?: string;
  externalRecovery?: boolean;
}>(), { submissionEnabled: true });
const emit = defineEmits<{ submitted: [run: RunDetail] }>();

const { providerName, runMessage, sourceName, t } = useLocale();
const route = useRoute();
const router = useRouter();
const readOnly = computed(() => props.mode === "run");

const sources = ref<SourceDescriptor[]>([]);
const sourceError = ref("");
const busy = ref(false);
const submitError = ref("");
const activeConflict = ref<RunDetail | null>(null);
const stopConflictBusy = ref(false);
const diagnosticsBusy = ref(false);
const diagnosticResult = ref<DiagnosticResult | null>(null);
const diagnosticError = ref("");

// Editable draft (edit mode). Kept alive across /search ↔ /runs/:id because both
// routes render this same component instance (§2.1 continuity).
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
  wosDb: "WOS",
  sourceContacts: { openalex_email: "", crossref_email: "", pubmed_email: "", pubmed_tool: "paperseek" },
  embeddingProvider: "local" as keyof typeof retrievalProviderDefaults,
  embeddingModel: "",
  embeddingBaseUrl: "",
  embeddingApiKey: "",
  rerankerProvider: "" as keyof typeof rerankerProviderDefaults,
  rerankerModel: "",
  rerankerBaseUrl: "",
  rerankerApiKey: "",
});

// Run-mode mirror: non-sensitive values restored from the server config_snapshot
// only; missing keys stay empty and render as "Not recorded" (§2.3).
const runForm = reactive({
  question: "",
  source: "",
  searchBudget: "",
  fieldHint: "",
  llmProvider: "",
  llmModel: "",
  llmApiType: "",
  llmBaseUrl: "",
  wosDb: "",
  sourceContacts: { openalex_email: "", crossref_email: "", pubmed_email: "", pubmed_tool: "" },
  embeddingProvider: "",
  embeddingModel: "",
  embeddingBaseUrl: "",
  rerankerProvider: "",
  rerankerModel: "",
  rerankerBaseUrl: "",
});
const snapshotCitation = ref<boolean | undefined>(undefined);
const snapshotFieldIds = ref<string[] | undefined>(undefined);

const activeForm = computed(() => (readOnly.value ? runForm : form));

watch(() => runState.run, (run) => {
  const snap = (run?.config_snapshot || {}) as Record<string, unknown>;
  runForm.question = run?.question || "";
  runForm.source = run?.source || "";
  runForm.searchBudget = typeof snap.search_budget === "string" ? snap.search_budget : "";
  runForm.fieldHint = typeof snap.field_hint === "string" ? snap.field_hint : "";
  runForm.wosDb = typeof snap.wos_db === "string" ? snap.wos_db : "";
  snapshotCitation.value = typeof snap.citation_enabled === "boolean" ? snap.citation_enabled : undefined;
  snapshotFieldIds.value = Array.isArray(snap.field_ids) ? snap.field_ids.map(String) : undefined;
  const llm = (snap.llm || {}) as Record<string, unknown>;
  runForm.llmProvider = typeof llm.provider === "string" ? llm.provider : "";
  runForm.llmModel = typeof llm.model === "string" ? llm.model : "";
  runForm.llmApiType = typeof llm.api_type === "string" ? llm.api_type : "";
  runForm.llmBaseUrl = typeof llm.base_url === "string" ? llm.base_url : "";
  const retrieval = (snap.retrieval || {}) as Record<string, unknown>;
  const embedding = (retrieval.embedding || {}) as Record<string, unknown>;
  runForm.embeddingProvider = typeof embedding.provider === "string" ? embedding.provider : "";
  runForm.embeddingModel = typeof embedding.model === "string" ? embedding.model : "";
  runForm.embeddingBaseUrl = typeof embedding.base_url === "string" ? embedding.base_url : "";
  const reranker = (retrieval.reranker || {}) as Record<string, unknown>;
  runForm.rerankerProvider = typeof reranker.provider === "string" ? reranker.provider : "";
  runForm.rerankerModel = typeof reranker.model === "string" ? reranker.model : "";
  runForm.rerankerBaseUrl = typeof reranker.base_url === "string" ? reranker.base_url : "";
  const contacts = (snap.source_contacts || {}) as Record<string, unknown>;
  runForm.sourceContacts.openalex_email = typeof contacts.openalex_email === "string" ? contacts.openalex_email : "";
  runForm.sourceContacts.crossref_email = typeof contacts.crossref_email === "string" ? contacts.crossref_email : "";
  runForm.sourceContacts.pubmed_email = typeof contacts.pubmed_email === "string" ? contacts.pubmed_email : "";
  runForm.sourceContacts.pubmed_tool = typeof contacts.pubmed_tool === "string" ? contacts.pubmed_tool : "";
}, { immediate: true });

const selectedSource = computed(() => sources.value.find((source) => source.id === activeForm.value.source));
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
const showCitation = computed(
  () => (readOnly.value ? snapshotCitation.value !== undefined : supportsCitationExpansion.value),
);
const budgetHintKey = computed(() => (({
  fast: "budgetHintFast",
  medium: "budgetHintMedium",
  high: "budgetHintHigh",
  max: "budgetHintMax",
}) as Record<string, string>)[activeForm.value.searchBudget || "fast"]);
const canSubmit = computed(
  () => !readOnly.value && props.submissionEnabled && Boolean(form.question.trim()) && !busy.value,
);

// Run-mode static field summary; names resolve through the source descriptor when
// available, otherwise the raw recorded ids are shown (§2.3).
const runFieldSummary = computed(() => {
  const ids = snapshotFieldIds.value;
  if (ids === undefined) return t("notRecorded");
  if (!ids.length) return t("fieldUnrestricted");
  const options = selectedFilter.value?.mode === "native" ? selectedFilter.value.options : [];
  const names = ids.map((id) => {
    const option = options.find((item) => item.id === id);
    return option ? option.label : id;
  });
  const shown = names.slice(0, 2);
  const rest = names.length - shown.length;
  if (rest > 0) shown.push(t("fieldSummaryMore").replace("{n}", String(rest)));
  return shown.join(t("fieldSummaryJoin"));
});
const showRunFieldSummary = computed(
  () => snapshotFieldIds.value !== undefined || selectedFilter.value?.mode === "native",
);

const missingRunProvider = computed(
  () => readOnly.value && !Object.keys(providerDefaults).includes(runForm.llmProvider),
);
const missingRunEmbeddingProvider = computed(
  () => readOnly.value && !Object.keys(retrievalProviderDefaults).includes(runForm.embeddingProvider),
);
const missingRunRerankerProvider = computed(
  () => readOnly.value && !Object.keys(rerankerProviderDefaults).includes(runForm.rerankerProvider),
);
const missingRunSource = computed(
  () => readOnly.value && Boolean(runForm.source) && !sources.value.some((source) => source.id === runForm.source),
);

// Sync flush: preset auto-fill applies before subsequent assignments, so rerun()
// can set the provider and then restore the recorded model/route values.
watch(() => form.llmProvider, (provider) => {
  const [model, apiType, baseUrl] = providerDefaults[provider];
  form.llmModel = model;
  form.llmApiType = apiType;
  form.llmBaseUrl = baseUrl;
}, { flush: "sync" });
watch(() => form.embeddingProvider, (provider) => {
  [form.embeddingModel, form.embeddingBaseUrl] = retrievalProviderDefaults[provider];
}, { flush: "sync" });
watch(() => form.rerankerProvider, (provider) => {
  [form.rerankerModel, form.rerankerBaseUrl] = rerankerProviderDefaults[provider];
}, { flush: "sync" });

watch(() => form.source, () => {
  form.fieldIds = [];
  form.fieldHint = "";
  form.sourceApiKey = "";
  form.citationEnabled = supportsCitationExpansion.value;
});

onMounted(async () => {
  if (!readOnly.value || !props.externalRecovery || props.sourceOptions) await loadSources();
});

watch(() => props.sourceOptions, value => { if (value) applySources(value); });
watch(() => props.service?.mode, clearCredentials);

function applySources(value: SourceDescriptor[]): void {
  sources.value = value;
  if (readOnly.value) return;
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
    if (readOnly.value) return;
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
    // Same component instance renders the run route: layout and scroll stay put (§2.1).
    await router.replace(`/runs/${run.id}`);
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
  if (readOnly.value) return;
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
      wos_db: form.wosDb,
      source_contacts: { ...form.sourceContacts },
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

const diagnosticContext = computed(() => ({
  source: form.source,
  sourceLabel: selectedSource.value?.label || "",
  llmProvider: form.llmProvider,
  sourceName,
  providerName,
}));

/* ---- Run mode (§2.2, §5) ---- */

const runId = computed(() => String(route.params.runId || ""));
const pageState = ref<"loading" | "error" | "loaded">("loading");
const status = computed(() => runState.run?.status || "");
const isActiveRun = computed(() => ["queued", "running", "cancelling"].includes(status.value));
const isTerminal = computed(() => ["completed", "completed_with_warnings", "failed", "cancelled"].includes(status.value));
const canStop = computed(() => ["queued", "running"].includes(status.value) || runState.cancelPending);
const statusBadgeClass = computed(() => {
  if (status.value === "failed" || status.value === "cancelled") return "badge--danger";
  if (["completed", "completed_with_warnings"].includes(status.value)) return "badge--success";
  if (isActiveRun.value) return "badge--accent";
  return "";
});

const stageLabels: Array<[StageKey, string]> = [
  ["query", "queryStage"],
  ["search", "searchStage"],
  ["ranking", "rankingStage"],
  ["results", "resultsStage"],
];
const activeStage = computed<StageKey | null>(
  () => (Object.keys(runState.stages) as StageKey[]).find((key) => runState.stages[key] === "active") || null,
);
const activeStageLabel = computed(() => {
  const found = stageLabels.find(([key]) => key === activeStage.value);
  return found ? t(found[1]) : "";
});

// Mobile sticky stage bar elapsed time; same server-time derivation as the stages (§6).
const now = ref(Date.now());
const timer = setInterval(() => {
  now.value = Date.now();
}, 1000);
onBeforeUnmount(() => clearInterval(timer));
const activeStageElapsed = computed(() => {
  if (!activeStage.value) return "";
  const startedAt = runState.stageStartedAt[activeStage.value];
  if (!startedAt) return "";
  const started = Date.parse(startedAt);
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
});

function scrollToCurrentStage(): void {
  if (!activeStage.value) return;
  document
    .querySelector(`[data-testid="stage-${activeStage.value}"]`)
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function stop(): Promise<void> {
  try {
    await cancelRun(runId.value);
  } catch (error) {
    if (!(error instanceof Error && error.name === "AbortError")) {
      runState.error = error instanceof Error ? error.message : "cancel_unavailable";
    }
  }
}

async function load(value: string): Promise<void> {
  if (!value) return;
  pageState.value = "loading";
  try {
    await recoverRun(value);
    if (runId.value === value) pageState.value = "loaded";
  } catch (error) {
    if (runId.value === value && !(error instanceof Error && error.name === "AbortError")) {
      runState.error = error instanceof Error ? error.message : "run_unavailable";
      pageState.value = "error";
    }
  }
}

watch([runId, () => props.mode], ([id, mode], previous) => {
  const previousMode = previous?.[1];
  if (mode !== "run") {
    if (previousMode === "run" && !props.externalRecovery) stopRunRecovery();
    return;
  }
  if (id && !props.externalRecovery) void load(id);
}, { immediate: true });

onBeforeUnmount(() => { if (props.mode === "run" && !props.externalRecovery) stopRunRecovery(); });

// "Edit and run again" copies the public configuration into a fresh draft without
// touching the finished run or auto-submitting (§2.2).
function rerun(): void {
  const run = runState.run;
  const snap = (run?.config_snapshot || {}) as Record<string, unknown>;
  if (run?.question) form.question = run.question;
  if (run?.source && sources.value.some((source) => source.id === run.source)) form.source = run.source;
  if (typeof snap.search_budget === "string" && ["fast", "medium", "high", "max"].includes(snap.search_budget)) {
    form.searchBudget = snap.search_budget as SearchSubmission["search_budget"];
  }
  if (Array.isArray(snap.field_ids)) form.fieldIds = snap.field_ids.map(String);
  if (typeof snap.field_hint === "string") form.fieldHint = snap.field_hint;
  if (typeof snap.citation_enabled === "boolean") form.citationEnabled = snap.citation_enabled;
  if (typeof snap.wos_db === "string") form.wosDb = snap.wos_db;
  const llm = snap.llm as Record<string, unknown> | undefined;
  if (llm && typeof llm.provider === "string" && llm.provider in providerDefaults) {
    form.llmProvider = llm.provider as keyof typeof providerDefaults;
    if (typeof llm.model === "string") form.llmModel = llm.model;
    if (typeof llm.api_type === "string") form.llmApiType = llm.api_type;
    if (typeof llm.base_url === "string") form.llmBaseUrl = llm.base_url;
  }
  const retrieval = snap.retrieval as Record<string, unknown> | undefined;
  const embedding = retrieval?.embedding as Record<string, unknown> | undefined;
  if (embedding && typeof embedding.provider === "string" && embedding.provider in retrievalProviderDefaults) {
    form.embeddingProvider = embedding.provider as keyof typeof retrievalProviderDefaults;
    if (typeof embedding.model === "string") form.embeddingModel = embedding.model;
    if (typeof embedding.base_url === "string") form.embeddingBaseUrl = embedding.base_url;
  }
  const reranker = retrieval?.reranker as Record<string, unknown> | undefined;
  if (reranker && typeof reranker.provider === "string" && reranker.provider in rerankerProviderDefaults) {
    form.rerankerProvider = reranker.provider as keyof typeof rerankerProviderDefaults;
    if (typeof reranker.model === "string") form.rerankerModel = reranker.model;
    if (typeof reranker.base_url === "string") form.rerankerBaseUrl = reranker.base_url;
  }
  const contacts = snap.source_contacts as Record<string, unknown> | undefined;
  if (contacts) {
    for (const key of ["openalex_email", "crossref_email", "pubmed_email", "pubmed_tool"] as const) {
      if (typeof contacts[key] === "string") form.sourceContacts[key] = contacts[key] as string;
    }
  }
  clearCredentials();
  void router.push("/search");
}
</script>

<template>
  <div class="workbench">
    <div class="workbench-pane workbench-pane--config">
      <div v-if="readOnly && pageState === 'loading' && !runState.run" class="state-block" data-testid="run-loading">
        <span>{{ t("active") }}…</span>
      </div>
      <div v-else-if="readOnly && pageState === 'error' && !runState.run" class="state-block state-block--error" role="alert">
        <strong>{{ t("loadError") }}</strong>
        <span>{{ t(runState.error || "run_unavailable") }}</span>
        <button class="button" type="button" @click="load(runId)">{{ t("retry") }}</button>
      </div>
      <form v-else class="search-form" :class="{ 'search-form--readonly': readOnly }" autocomplete="off" novalidate @submit.prevent="submit" @keydown="onSubmitShortcut">
        <div v-if="readOnly" class="run-panel-primary" data-testid="run-primary-summary">
          <div class="run-status-line">
            <span class="badge" :class="statusBadgeClass"><strong data-testid="run-status">{{ t(status || "unavailable") }}</strong></span>
          </div>
          <p v-if="runState.run?.error_code" class="alert" role="alert">{{ runMessage(runState.run.error_code, "error") }}</p>
          <dl class="run-panel-facts">
            <div class="fact"><dt>{{ t("resultCount") }}</dt><dd>{{ runState.run?.result_count ?? 0 }}</dd></div>
          </dl>
          <ul v-if="runState.run?.warnings?.length" class="run-warnings" data-testid="run-warnings">
            <li v-for="warning in runState.run.warnings" :key="warning">{{ runMessage(warning) }}</li>
          </ul>
        </div>
        <section class="form-section form-section--flat" :aria-label="t('searchControls')">
          <div class="field">
            <label class="field-label" for="research-question">{{ t("researchQuestion") }}</label>
            <textarea
              id="research-question"
              v-model="activeForm.question"
              rows="4"
              required
              :maxlength="QUESTION_MAX_LENGTH"
              :disabled="readOnly"
              :placeholder="readOnly ? t('notRecorded') : t('questionPlaceholder')"
            ></textarea>
            <span v-if="!readOnly" class="question-count">{{ form.question.length }} / {{ QUESTION_MAX_LENGTH }} {{ t("questionCountLabel") }}</span>
          </div>
          <label class="field">
            <span class="field-label">{{ t("dataSource") }}</span>
            <select v-model="activeForm.source" :disabled="readOnly">
              <option v-if="missingRunSource" :value="runForm.source">{{ sourceName(runForm.source) }}</option>
              <option v-for="source in sources" :key="source.id" :value="source.id">{{ sourceName(source.id, source.label) }}</option>
            </select>
          </label>
          <slot v-if="!readOnly" name="source-note" :source="selectedSource" />
          <div v-if="!readOnly && sourceError" class="alert" role="alert">
            <strong>{{ t("sources_unavailable") }}</strong>
            <div class="alert-actions">
              <button class="button button--small" type="button" @click="loadSources">{{ t("retry") }}</button>
            </div>
          </div>
          <fieldset class="filter-group">
            <legend>{{ t("searchBudget") }}</legend>
            <div class="segmented budget-segmented">
              <label v-for="budget in ['fast', 'medium', 'high', 'max']" :key="budget">
                <input v-model="activeForm.searchBudget" type="radio" name="searchBudget" :value="budget" :disabled="readOnly" />
                <span>{{ t(budget) }}</span>
              </label>
            </div>
            <p class="budget-hint">{{ readOnly && !activeForm.searchBudget ? t("notRecorded") : t(budgetHintKey) }}</p>
          </fieldset>
          <FieldSelector
            v-if="!readOnly && selectedFilter?.mode === 'native'"
            :source-id="form.source"
            :label="selectedFilterLabel"
            :options="selectedFilter.options"
            :model-value="form.fieldIds"
            @update:model-value="form.fieldIds = $event"
          />
          <div v-else-if="readOnly && showRunFieldSummary" class="field field-selector-static" data-testid="source-filter">
            <span class="field-label">{{ selectedFilterLabel }}</span>
            <span class="field-selector-value">{{ runFieldSummary }}</span>
          </div>
          <label
            v-else-if="selectedFilter?.mode === 'text'"
            class="field"
            data-testid="source-filter"
          >
            <span class="field-label">{{ selectedFilterLabel }}</span>
            <input v-model="activeForm.fieldHint" type="text" autocomplete="off" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" />
          </label>
          <label v-if="showCitation" class="toggle-field">
            <input v-if="!readOnly" v-model="form.citationEnabled" type="checkbox" />
            <input v-else type="checkbox" :checked="snapshotCitation === true" disabled />
            <span><strong>{{ t("expandCitations") }}</strong><small>{{ t("citationHelp") }}</small></span>
          </label>
          <div
            v-if="!readOnly && selectedSource?.credential"
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

        <slot v-if="!readOnly" name="service-mode" />
        <section class="form-section" :aria-label="t('modelConfiguration')">
          <div v-show="!modelSettings" style="display: contents">
          <div>
            <div class="section-kicker">{{ t("configuration") }}</div>
            <h2 class="section-title">{{ t("modelSource") }}</h2>
          </div>
          <div class="field-grid">
            <label class="field span-2"><span class="field-label">{{ t("provider") }}</span>
              <select v-model="activeForm.llmProvider" :disabled="readOnly">
                <option v-if="missingRunProvider" :value="runForm.llmProvider">{{ runForm.llmProvider ? providerName(runForm.llmProvider) : t("notRecorded") }}</option>
                <option v-for="provider in Object.keys(providerDefaults)" :key="provider" :value="provider">{{ providerName(provider) }}</option>
              </select>
            </label>
            <label class="field"><span class="field-label">{{ t("model") }}</span><input v-model="activeForm.llmModel" type="text" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" /></label>
            <div class="field">
              <label class="field">
                <span class="field-label">{{ t("apiKey") }}</span>
                <input v-if="!readOnly" v-model="form.llmApiKey" type="password" autocomplete="off" />
                <input v-else type="password" value="" disabled autocomplete="off" />
              </label>
              <span class="field-help">{{ readOnly ? t("credentialSubmitted") : (credentialHelp || t("credentialHelp")) }}</span>
            </div>
          </div>
          </div>
          <template v-if="!readOnly">
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
                    <span>{{ diagnosticSummary(t, diagnosticContext, check) }}</span>
                    <ul v-if="diagnosticActions(t, check).length" class="diagnostics-actions">
                      <li v-for="action in diagnosticActions(t, check)" :key="action">{{ action }}</li>
                    </ul>
                  </div>
                </li>
              </ul>
            </div>
            <div v-if="diagnosticError" class="alert" role="alert">
              <strong>{{ t("diagnostics_unavailable") }}</strong>
            </div>
          </template>
        </section>

        <div class="form-actions">
          <template v-if="!readOnly">
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
          </template>
          <template v-else>
            <button
              v-if="canStop"
              class="button button--danger"
              type="button"
              :disabled="runState.cancelPending"
              @click="stop"
            >{{ runState.cancelPending ? t("stopping") : t("stop") }}</button>
            <button v-else-if="isTerminal" class="button button--primary" type="button" data-testid="rerun-edit" @click="rerun">{{ t("rerunWithChanges") }}</button>
            <div
              v-if="isActiveRun && runState.connection !== 'connected'"
              class="connection-notice"
              data-testid="connection-notice"
              role="status"
            >
              {{ runState.connection === "offline" ? t("connectionOffline") : t("connectionReconnecting") }}
            </div>
          </template>
        </div>

        <details v-show="!modelSettings" class="advanced-section">
          <summary>
            <svg class="disclosure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
            <span>{{ t("advanced") }}</span>
          </summary>
          <div class="advanced-body">
            <div v-if="['openalex', 'crossref', 'pubmed', 'wos'].includes(activeForm.source)" class="field-grid">
              <label v-if="activeForm.source === 'openalex'" class="field"><span class="field-label">{{ t("openAlexEmail") }}</span>
                <input v-model="activeForm.sourceContacts.openalex_email" type="email" maxlength="320" autocomplete="off" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" />
              </label>
              <label v-if="activeForm.source === 'crossref'" class="field"><span class="field-label">{{ t("crossrefEmail") }}</span>
                <input v-model="activeForm.sourceContacts.crossref_email" type="email" maxlength="320" autocomplete="off" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" />
              </label>
              <label v-if="activeForm.source === 'pubmed'" class="field"><span class="field-label">{{ t("pubmedEmail") }}</span>
                <input v-model="activeForm.sourceContacts.pubmed_email" type="email" maxlength="320" autocomplete="off" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" />
              </label>
              <label v-if="activeForm.source === 'pubmed'" class="field"><span class="field-label">{{ t("pubmedTool") }}</span>
                <input v-model="activeForm.sourceContacts.pubmed_tool" type="text" maxlength="128" autocomplete="off" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" />
              </label>
              <label v-if="activeForm.source === 'wos'" class="field"><span class="field-label">{{ t("wosDatabase") }}</span>
                <input v-model="activeForm.wosDb" type="text" maxlength="64" autocomplete="off" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" />
              </label>
            </div>
            <div class="field-grid">
              <label class="field"><span class="field-label">{{ t("apiType") }}</span>
                <select v-model="activeForm.llmApiType" :disabled="readOnly">
                  <option v-if="readOnly && !['openai_chat', 'openai_responses', 'anthropic_messages'].includes(runForm.llmApiType)" :value="runForm.llmApiType">{{ runForm.llmApiType || t("notRecorded") }}</option>
                  <option value="openai_chat">OpenAI Chat Completions</option>
                  <option value="openai_responses">OpenAI Responses</option>
                  <option value="anthropic_messages">Anthropic Messages</option>
                </select>
              </label>
              <label class="field"><span class="field-label">{{ t("baseUrl") }}</span><input v-model="activeForm.llmBaseUrl" type="url" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" /></label>
            </div>
            <div class="field-grid">
              <label class="field"><span class="field-label">{{ t("embeddingProvider") }}</span>
                <select v-model="activeForm.embeddingProvider" :disabled="readOnly">
                  <option v-if="missingRunEmbeddingProvider" :value="runForm.embeddingProvider">{{ runForm.embeddingProvider ? providerName(runForm.embeddingProvider) : t("notRecorded") }}</option>
                  <option v-for="provider in Object.keys(retrievalProviderDefaults)" :key="provider" :value="provider">{{ providerName(provider) }}</option>
                </select>
              </label>
              <label class="field"><span class="field-label">{{ t("embeddingModel") }}</span><input v-model="activeForm.embeddingModel" type="text" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" /></label>
              <label class="field"><span class="field-label">{{ t("embeddingBaseUrl") }}</span><input v-model="activeForm.embeddingBaseUrl" type="url" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" /></label>
              <div v-if="!readOnly" class="field">
                <label class="field">
                  <span class="field-label">{{ t("embeddingApiKey") }}</span>
                  <input v-model="form.embeddingApiKey" type="password" autocomplete="off" />
                </label>
                <span class="field-help">{{ credentialHelp || t("credentialHelp") }}</span>
              </div>
              <label class="field"><span class="field-label">{{ t("rerankerProvider") }}</span>
                <select v-model="activeForm.rerankerProvider" :disabled="readOnly">
                  <option v-if="missingRunRerankerProvider" :value="runForm.rerankerProvider">{{ runForm.rerankerProvider ? providerName(runForm.rerankerProvider) : t("notRecorded") }}</option>
                  <option value="">{{ t("off") }}</option>
                  <option v-for="provider in Object.keys(rerankerProviderDefaults).filter((value) => value)" :key="provider" :value="provider">{{ providerName(provider) }}</option>
                </select>
              </label>
              <label class="field"><span class="field-label">{{ t("rerankerModel") }}</span><input v-model="activeForm.rerankerModel" type="text" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" /></label>
              <label class="field"><span class="field-label">{{ t("rerankerBaseUrl") }}</span><input v-model="activeForm.rerankerBaseUrl" type="url" :disabled="readOnly" :placeholder="readOnly ? t('notRecorded') : undefined" /></label>
              <div v-if="!readOnly" class="field">
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
      <button
        v-if="readOnly && activeStage && isActiveRun"
        class="mobile-stage-bar"
        type="button"
        :aria-label="`${t('goToCurrentStage')}: ${activeStageLabel}`"
        @click="scrollToCurrentStage"
      >
        <span class="nav-run-dot" aria-hidden="true"></span>
        <span>{{ activeStageLabel }}</span>
        <span v-if="activeStageElapsed" class="stage-elapsed">{{ activeStageElapsed }}</span>
      </button>
      <WorkflowStages>
        <template v-if="$slots['log-export']" #log-export="scope"><slot name="log-export" v-bind="scope" /></template>
      </WorkflowStages>
    </div>
  </div>
</template>
