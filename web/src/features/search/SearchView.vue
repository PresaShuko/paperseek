<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

import { api } from "../../api/client";
import type { SearchSubmission, SourceDescriptor } from "../../api/types";
import { useLocale } from "../../locales";
import { runState, startSearch } from "../../state/run";
import WorkflowStages from "./WorkflowStages.vue";

const { t } = useLocale();
const sources = ref<SourceDescriptor[]>([]);
const sourceError = ref("");
const busy = ref(false);
const providerDefaults = {
  openai: ["gpt-5.4-mini", "openai_responses", "https://api.openai.com/v1"],
  anthropic: ["claude-sonnet-4-6", "anthropic_messages", "https://api.anthropic.com"],
  google: ["gemini-3.5-flash", "openai_chat", "https://generativelanguage.googleapis.com/v1beta/openai"],
  deepseek: ["deepseek-v4-flash", "openai_chat", "https://api.deepseek.com"],
  cstcloud: ["deepseek-v4-flash", "openai_chat", "https://uni-api.cstcloud.cn/v1"],
  dashscope: ["qwen3.6-plus", "openai_chat", "https://dashscope.aliyuncs.com/compatible-mode/v1"],
  moonshot: ["kimi-k2.6", "openai_chat", "https://api.moonshot.ai/v1"],
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
const form = reactive({
  question: "",
  source: "openalex",
  searchBudget: "fast" as SearchSubmission["search_budget"],
  field: "",
  citationEnabled: true,
  llmProvider: "openai" as keyof typeof providerDefaults,
  llmApiType: "openai_responses",
  llmBaseUrl: "https://api.openai.com/v1",
  llmModel: "gpt-5.4-mini",
  llmApiKey: "",
  sourceApiKey: "",
});

watch(() => form.llmProvider, (provider) => {
  const [model, apiType, baseUrl] = providerDefaults[provider];
  form.llmModel = model;
  form.llmApiType = apiType;
  form.llmBaseUrl = baseUrl;
});

const status = computed(() => runState.run?.status || "ready");

onMounted(async () => {
  try {
    sources.value = await api.sources();
  } catch (error) {
    sourceError.value = error instanceof Error ? error.message : "sources_unavailable";
  }
});

async function submit(): Promise<void> {
  busy.value = true;
  try {
    await startSearch({
      question: form.question,
      source: form.source,
      search_budget: form.searchBudget,
      field: form.field,
      citation_enabled: form.citationEnabled,
      llm: {
        provider: form.llmProvider,
        api_type: form.llmApiType,
        base_url: form.llmBaseUrl,
        model: form.llmModel,
      },
      credentials: {
        llm: { api_key: form.llmApiKey },
        source: { api_key: form.sourceApiKey },
      },
    });
  } finally {
    busy.value = false;
    form.llmApiKey = "";
    form.sourceApiKey = "";
  }
}
</script>

<template>
  <main class="shell">
    <section class="left-pane" aria-label="Search controls">
      <form autocomplete="off" novalidate @submit.prevent="submit">
        <section class="query-section">
          <label class="m4-question-label" for="research-question">{{ t("researchQuestion") }}</label>
          <textarea
            id="research-question"
            v-model="form.question"
            rows="3"
            required
            :placeholder="t('questionPlaceholder')"
          ></textarea>
          <label class="field query-source-field">
            <span>{{ t("dataSource") }}</span>
            <select v-model="form.source">
              <option v-for="source in sources" :key="source.id" :value="source.id">{{ source.label }}</option>
            </select>
          </label>
          <p v-if="sourceError" class="config-alert-list" role="alert">{{ sourceError }}</p>
          <fieldset class="budget-field">
            <legend>{{ t("searchBudget") }}</legend>
            <div class="budget-segmented">
              <label v-for="budget in ['fast', 'medium', 'high', 'max']" :key="budget">
                <input v-model="form.searchBudget" type="radio" name="searchBudget" :value="budget" />
                <span>{{ t(budget) }}</span>
              </label>
            </div>
          </fieldset>
          <label class="field source-filter-text">
            <span>{{ t("fieldHint") }}</span>
            <input v-model="form.field" type="text" autocomplete="off" />
          </label>
          <label class="toggle-field citation-toggle">
            <input v-model="form.citationEnabled" type="checkbox" />
            <span><strong>{{ t("expandCitations") }}</strong><small>{{ t("citationHelp") }}</small></span>
          </label>
          <div class="query-actions">
            <button class="primary-button" type="submit" :disabled="busy || !form.question.trim()">
              <span>{{ t("runSearch") }}</span><span aria-hidden="true">→</span>
            </button>
            <button class="secondary-button" type="button" disabled>{{ t("stop") }}</button>
          </div>
        </section>
        <section class="config-section">
          <div class="section-header">
            <div><div class="section-kicker">{{ t("configuration") }}</div><h2>{{ t("modelSource") }}</h2></div>
            <span class="privacy-pill">{{ t("sessionOnly") }}</span>
          </div>
          <div class="field-grid">
            <label class="field span-2"><span>{{ t("provider") }}</span>
              <select v-model="form.llmProvider">
                <option value="openai">OpenAI</option><option value="anthropic">Anthropic</option>
                <option value="google">Google Gemini</option><option value="deepseek">DeepSeek</option>
                <option value="cstcloud">CSTCloud</option><option value="dashscope">Alibaba Cloud Bailian</option>
                <option value="moonshot">Kimi</option><option value="zhipu">Zhipu AI</option>
                <option value="siliconflow">SiliconFlow</option><option value="openrouter">OpenRouter</option>
                <option value="nvidia">NVIDIA NIM</option><option value="volcengine">Volcano Ark</option>
                <option value="hunyuan">Tencent Hunyuan</option><option value="qianfan">Baidu Qianfan</option>
                <option value="modelscope">ModelScope API-Inference</option><option value="ollama">Ollama</option>
                <option value="custom">Custom</option>
              </select>
            </label>
            <label class="field"><span>{{ t("model") }}</span><input v-model="form.llmModel" type="text" /></label>
            <label class="field"><span>{{ t("apiKey") }}</span><input v-model="form.llmApiKey" type="password" autocomplete="off" /></label>
          </div>
          <details class="config-advanced">
            <summary><span>{{ t("advanced") }}</span></summary>
            <div class="config-advanced-body field-grid">
              <label class="field"><span>{{ t("apiType") }}</span>
                <select v-model="form.llmApiType">
                  <option value="openai_chat">OpenAI Chat Completions</option>
                  <option value="openai_responses">OpenAI Responses</option>
                  <option value="anthropic_messages">Anthropic Messages</option>
                </select>
              </label>
              <label class="field"><span>{{ t("baseUrl") }}</span><input v-model="form.llmBaseUrl" type="url" /></label>
              <label class="field span-2"><span>{{ t("sourceKey") }}</span><input v-model="form.sourceApiKey" type="password" autocomplete="off" /></label>
            </div>
          </details>
        </section>
      </form>
    </section>
    <section class="right-pane" aria-label="Workflow and results">
      <div class="m4-run-summary">
        <span>{{ runState.run?.id || "idle" }}</span>
        <strong data-testid="run-status">{{ t(status) }}</strong>
      </div>
      <WorkflowStages />
    </section>
  </main>
</template>
