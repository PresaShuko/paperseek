// Generated from paperseek_app.configuration. Do not edit.

export const providerDefaults = {
  "openai": ["gpt-5.6-luna", "openai_responses", "https://api.openai.com/v1"],
  "anthropic": ["claude-haiku-4-5", "anthropic_messages", "https://api.anthropic.com"],
  "google": ["gemini-3.5-flash", "openai_chat", "https://generativelanguage.googleapis.com/v1beta/openai"],
  "deepseek": ["deepseek-flash", "openai_chat", "https://api.deepseek.com"],
  "cstcloud": ["deepseek-v4-flash", "openai_chat", "https://uni-api.cstcloud.cn/v1"],
  "dashscope": ["qwen3.8-flash", "openai_chat", "https://dashscope.aliyuncs.com/compatible-mode/v1"],
  "moonshot": ["kimi-k2.6", "openai_chat", "https://api.moonshot.cn/v1"],
  "zhipu": ["glm-5.3-flash", "openai_chat", "https://open.bigmodel.cn/api/paas/v4"],
  "siliconflow": ["deepseek-ai/DeepSeek-V4-Flash", "openai_chat", "https://api.siliconflow.cn/v1"],
  "openrouter": ["openai/gpt-5.6-luna", "openai_chat", "https://openrouter.ai/api/v1"],
  "nvidia": ["nvidia/llama-3.3-nemotron-super-49b-v1.5", "openai_chat", "https://integrate.api.nvidia.com/v1"],
  "volcengine": ["doubao-seed-2-0-mini-260428", "openai_chat", "https://ark.cn-beijing.volces.com/api/v3"],
  "hunyuan": ["hunyuan-turbos-latest", "openai_chat", "https://tokenhub.tencentmaas.com/v1"],
  "qianfan": ["ernie-5.0", "openai_chat", "https://qianfan.baidubce.com/v2"],
  "modelscope": ["Qwen/Qwen3-235B-A22B-Instruct-2507", "openai_chat", "https://api-inference.modelscope.cn/v1"],
  "ollama": ["qwen3:8b", "openai_chat", "http://127.0.0.1:11434/v1"],
  "custom": ["", "openai_chat", ""],
} as const;

export const retrievalProviderDefaults = {
  "local": ["", ""],
  "cstcloud": ["qwen3-embedding:8b,bge-large-zh:latest", "https://uni-api.cstcloud.cn/v1"],
  "openai": ["text-embedding-3-large", "https://api.openai.com/v1"],
  "dashscope": ["text-embedding-v4", "https://dashscope.aliyuncs.com/compatible-mode/v1"],
  "siliconflow": ["BAAI/bge-m3", "https://api.siliconflow.cn/v1"],
  "openrouter": ["openai/text-embedding-3-small", "https://openrouter.ai/api/v1"],
  "nvidia": ["nvidia/nv-embedqa-e5-v5", "https://integrate.api.nvidia.com/v1"],
  "zhipu": ["embedding-3", "https://open.bigmodel.cn/api/paas/v4"],
  "volcengine": ["", "https://ark.cn-beijing.volces.com/api/v3"],
  "modelscope": ["Qwen/Qwen3-Embedding-8B,Qwen/Qwen3-Embedding-4B", "https://api-inference.modelscope.cn/v1"],
  "custom": ["", ""],
} as const;

export const rerankerProviderDefaults = {
  "": ["", ""],
  "cstcloud": ["qwen3-reranker:8b", "https://uni-api.cstcloud.cn/v1"],
  "openrouter": ["jinaai/jina-reranker-v2-base-multilingual", "https://openrouter.ai/api/v1"],
  "nvidia": ["nv-rerank-qa-mistral-4b:1", "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"],
  "siliconflow": ["BAAI/bge-reranker-v2-m3", "https://api.siliconflow.cn/v1"],
  "custom": ["", ""],
} as const;

export const decisionProviderDefaults = {
  "typesafe": ["jev-latest", "https://api.typesafe.ai/v1"],
  "siliconflow": ["SemIf", "https://api.siliconflow.cn/v1"],
} as const;

export const decisionModelOptions = {
  "typesafe": ["jev-latest", "jev-1.13.0"],
  "siliconflow": ["SemIf", "Kev-4B", "diffusiongemma"],
} as const;
