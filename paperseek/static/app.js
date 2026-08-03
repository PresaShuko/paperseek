const form = document.getElementById("searchForm");
const workflow = document.getElementById("workflow");
const logOutput = document.getElementById("logOutput");
const rightPane = document.getElementById("rightPane");
const logPanel = document.getElementById("logPanel");
const logToggle = document.getElementById("logToggle");
const logErrorBadge = document.getElementById("logErrorBadge");
const runId = document.getElementById("runId");
const stateLabel = document.getElementById("stateLabel");
const stepLabel = document.getElementById("stepLabel");
const searchButton = document.getElementById("searchButton");
const stopButton = document.getElementById("stopButton");
const dataSourceSelect = document.getElementById("dataSource");
const searchBudgetInputs = [...document.querySelectorAll("input[name='searchBudget']")];
const searchBudgetHelp = document.getElementById("searchBudgetHelp");
const providerSelect = document.getElementById("llmProvider");
const apiTypeSelect = document.getElementById("llmApiType");
const modelInput = document.getElementById("llmModel");
const baseUrlInput = document.getElementById("llmBaseUrl");
const retrievalEmbeddingProviderSelect = document.getElementById("retrievalEmbeddingProvider");
const retrievalEmbeddingModelInput = document.getElementById("retrievalEmbeddingModel");
const retrievalEmbeddingBaseUrlInput = document.getElementById("retrievalEmbeddingBaseUrl");
const retrievalRerankerProviderSelect = document.getElementById("retrievalRerankerProvider");
const retrievalRerankerModelInput = document.getElementById("retrievalRerankerModel");
const retrievalRerankerBaseUrlInput = document.getElementById("retrievalRerankerBaseUrl");
const exportLogButton = document.getElementById("exportLogButton");
const checkConfigButton = document.getElementById("checkConfigButton");
const disciplinePicker = document.getElementById("disciplinePicker");
const disciplinePickerLabel = document.getElementById("disciplinePickerLabel");
const disciplineOptionsContainer = document.getElementById("disciplineOptions");
const disciplineSummary = document.getElementById("disciplineSummary");
const clearDisciplinesButton = document.getElementById("clearDisciplinesButton");
const fieldHintField = document.getElementById("fieldHintField");
const fieldHintLabel = document.getElementById("fieldHintLabel");
const viewTabs = [...document.querySelectorAll(".mode-tabs .tab")];
const basicSourceName = document.getElementById("basicSourceName");
const basicSourceMeta = document.getElementById("basicSourceMeta");
const advancedSettings = document.getElementById("advancedSettings");
const configAlert = document.getElementById("configAlert");
const configAlertTitle = document.getElementById("configAlertTitle");
const configAlertMessage = document.getElementById("configAlertMessage");
const configAlertList = document.getElementById("configAlertList");
const configAlertCloseButton = document.getElementById("configAlertCloseButton");
const configAlertAdvancedButton = document.getElementById("configAlertAdvancedButton");
const languageButtons = [...document.querySelectorAll("[data-language]")];
const languageStorageKey = "paperseek.ui.language";

const translations = {
  zh: {
    "LLM based Literature Search Agent": "基于大模型的文献检索助手",
    "Search": "检索",
    "Results": "结果",
    "Citation Map": "引用图谱",
    "History": "历史",
    "Resume from checkpoint": "从检查点继续",
    "Checkpoint": "检查点",
    "Export Results CSV": "导出结果 CSV",
    "Export Log": "导出日志",
    "Ready": "就绪",
    "Processing": "处理中",
    "Searching": "检索中",
    "Stopping": "停止中",
    "Stopped": "已停止",
    "Error": "错误",
    "Research Question": "研究问题",
    "Search budget": "检索预算",
    "Fast": "快速",
    "Medium": "中",
    "High": "高",
    "Max": "最大",
    "Fewest requests for faster searches.": "请求次数最少，检索更快。",
    "Balanced recall, ranking depth, and API use. Recommended.": "在召回范围、排序深度和 API 使用量之间取得平衡，推荐使用。",
    "Wider recall and deeper citation traversal; takes longer.": "扩大召回范围并加深引用遍历，耗时更长。",
    "Largest candidate and ranking budget; intended for difficult searches.": "使用最大的候选池和排序预算，适合较困难的检索。",
    "Paste a research question, gap paragraph, or plain language search intent.": "粘贴研究问题、研究空白段落，或用自然语言描述检索意图。",
    "Discipline Fields": "学科领域",
    "Any field": "不限学科",
    "Source Filter": "数据源筛选",
    "Any filter": "不限筛选",
    "Field/context hint": "领域/语境提示",
    "OpenAlex Field": "OpenAlex 学科",
    "Web of Science Category": "Web of Science 分类",
    "arXiv Category": "arXiv 分类",
    "Computer science top conferences": "计算机顶会",
    "Loading discipline fields...": "正在加载学科领域...",
    "Discipline fields unavailable": "学科领域暂不可用",
    "Run Search": "开始检索",
    "Stop": "停止",
    "Check Config": "检查配置",
    "Configuration": "配置",
    "Model API and source": "模型 API 与数据源",
    "Session only": "仅本次会话",
    "Model API": "模型 API",
    "Provider": "服务商",
    "API Key": "API Key",
    "Model": "模型",
    "Source": "数据源",
    "OpenAlex": "OpenAlex",
    "OpenAlex (precise search)": "OpenAlex（精确检索）",
    "arXiv (preprints)": "arXiv（预印本）",
    "Semantic Scholar (broad scholarly graph)": "Semantic Scholar（广域学术图谱）",
    "PubMed (biomedical literature)": "PubMed（生物医学文献）",
    "Google Scholar (via Serper)": "Google Scholar（通过 Serper）",
    "Crossref (metadata / DOI registry)": "Crossref（元数据 / DOI 注册库）",
    "Web of Science Starter (temporarily unavailable)": "Web of Science Starter（暂不可用）",
    "Optional source keys are in Advanced settings.": "可选数据源 Key 在高级设置中。",
    "Optional OpenAlex API key and email are in Advanced settings.": "可选 OpenAlex API Key 和邮箱在高级设置中。",
    "Crossref email is optional but recommended in Advanced settings.": "Crossref 邮箱可选，但建议在高级设置中填写。",
    "Google Scholar requires a Serper API key in Advanced settings.": "Google Scholar 需要在高级设置中填写 Serper API Key。",
    "Serper API Key": "Serper API Key",
    "Required for Google Scholar": "Google Scholar 必填",
    "WoS requires an API key in Advanced settings.": "WoS 需要在高级设置中填写 API Key。",
    "Source details are in Advanced settings.": "数据源详情在高级设置中。",
    "Advanced settings": "高级设置",
    "Protocol, source keys, and run controls": "协议、数据源 Key 和运行控制",
    "Protocol, source keys, and retrieval settings": "协议、数据源 Key 和检索重排设置",
    "Model protocol": "模型协议",
    "API Type": "API 类型",
    "OpenAI Responses API": "OpenAI Responses API",
    "OpenAI Chat Completions API": "OpenAI Chat Completions API",
    "Anthropic Messages API": "Anthropic Messages API",
    "Base URL": "Base URL",
    "Provider default, editable for compatible endpoints": "服务商默认地址，可为兼容端点修改",
    "Source settings": "数据源设置",
    "Data Source": "数据源",
    "OpenAlex API Key": "OpenAlex API Key",
    "Optional if anonymous access is available": "匿名访问可用时可选",
    "OpenAlex Email": "OpenAlex 邮箱",
    "Optional polite-pool email": "可选 polite-pool 邮箱",
    "Crossref Email": "Crossref 邮箱",
    "WoS API Key": "WoS API Key",
    "WoS DB": "WoS 数据库",
    "Field Hint": "领域提示",
    "Optional discipline": "可选学科领域",
    "Run controls": "运行控制",
    "Min Results": "最少结果",
    "Max Results": "最多结果",
    "Iterations": "迭代次数",
    "Try external abstracts": "尝试外部摘要",
    "Expand citations": "扩展引用",
    "Adds forward and backward citation traversal; searches may take longer.": "会进行前后向引用遍历，检索耗时可能增加。",
    "System Dashboard": "系统面板",
    "System Log": "系统日志",
    "Expand system log": "展开系统日志",
    "Collapse system log": "收起系统日志",
    "idle": "空闲",
    "Configuration check": "配置检查",
    "Configuration failed": "配置失败",
    "Configuration check failed": "配置检查失败",
    "PaperSeek found a configuration issue.": "PaperSeek 发现配置问题。",
    "Open Advanced Settings": "打开高级设置",
    "Close": "关闭",
    "Query Generation": "查询生成",
    "Search Intent & Query": "检索意图与检索式",
    "LLM will translate the research question into a source-specific search query.": "LLM 会把研究问题转换成适配数据源的检索式。",
    "No query generated yet.": "尚未生成检索式。",
    "Source Request": "数据源请求",
    "Search Iteration": "检索迭代",
    "The selected database will be queried and adjusted by result counts.": "系统会查询所选数据库，并根据结果数量调整检索式。",
    "No source request has run.": "尚未请求数据源。",
    "Metadata Ranking": "元数据排序",
    "Candidate Retrieval & Ranking": "候选召回与排序",
    "Returned records will be ranked with available metadata and abstracts when present.": "返回记录会基于可用元数据和摘要进行排序。",
    "No ranking request has run.": "尚未执行排序。",
    "Literature Results": "文献结果",
    "Final ranked papers will appear here.": "最终排序后的论文会显示在这里。",
    "Run a search to populate the result list.": "运行检索后会填充结果列表。",
    "WAITING": "等待中",
    "PROCESSING": "处理中",
    "COMPLETE": "已完成",
    "READY": "就绪",
    "EMPTY": "空",
    "ERROR": "错误",
    "Calling the LLM to generate a source-specific query.": "正在调用 LLM 生成适配数据源的检索式。",
    "No query returned": "未返回检索式",
    "CANDIDATES": "候选",
    "RANKED RECORDS": "已排序记录",
    "RANKING STATUS": "排序状态",
    "SOURCE": "数据源",
    "TOTAL RECORDS": "总记录",
    "TOP SCORE": "最高分",
    "CANDIDATES SCORED": "已评分候选",
    "CANDIDATE POOL": "候选池",
    "CITATION ADDS": "引用新增",
    "SOURCE HITS": "数据源命中",
    "FUSED CANDIDATES": "融合候选",
    "ITERATIONS": "迭代轮数",
    "FINAL HITS": "最终命中",
    "FINAL ACTION": "最终动作",
    "SCORED >= 5": "5 分及以上",
    "LEDGER CANDIDATES": "账本候选",
    "SELECTED FOR LLM": "送入 LLM",
    "FINAL OUTPUT": "最终输出",
    "Review Results": "查看结果",
    "Open Citation Map": "打开引用图谱",
    "Input Required": "需要输入",
    "Fill the required field and run the search again.": "请填写必填字段后重新运行检索。",
    "Search Failed": "检索失败",
    "The local backend or upstream service returned an error.": "本地后端或上游服务返回错误。",
    "Search Stopped": "检索已停止",
    "The request was stopped before completion.": "请求在完成前已停止。",
    "No final result was produced for this run.": "本次运行没有生成最终结果。",
    "Research Question is required.": "请填写研究问题。",
    "WoS API Key is required for WoS searches.": "WoS 检索需要 WoS API Key。",
    "Serper API Key is required for Google Scholar searches.": "Google Scholar 检索需要 Serper API Key。",
    "LLM API Key is required for this provider.": "当前服务商需要 LLM API Key。",
    "API Type is required.": "请填写 API 类型。",
    "Min Results and Max Results must be numbers.": "最少结果和最多结果必须是数字。",
    "Min Results cannot exceed Max Results.": "最少结果不能大于最多结果。",
    "Iterations must be at least 1.": "迭代次数至少为 1。",
    "Configuration check started.": "配置检查已开始。",
    "Fix the items below before running a search.": "请先修复以下项目，再运行检索。",
    "PaperSeek could not complete the configuration check.": "PaperSeek 无法完成配置检查。",
    "Configuration check failed.": "配置检查失败。",
    "Review the required model and source settings, then run Check Config again.": "检查必需的模型和数据源设置，然后再次运行检查配置。",
    "TARGET_MIN cannot exceed TARGET_MAX.": "TARGET_MIN 不能大于 TARGET_MAX。",
    "Lower TARGET_MIN or raise TARGET_MAX.": "降低 TARGET_MIN 或提高 TARGET_MAX。",
    "LLM_BASE_URL is empty; provider defaults will be used when available.": "LLM_BASE_URL 为空；可用时将使用服务商默认地址。",
    "Waiting for the first source response.": "正在等待首次数据源响应。",
    "Current query": "当前检索式",
    "Candidate preview": "候选预览",
    "No ranked papers returned.": "未返回排序论文。",
    "No author metadata": "无作者元数据",
    "Open source record": "打开来源记录",
    "Open PDF": "打开 PDF",
    "Keywords:": "关键词：",
    "Citations:": "引用数：",
    "Abstract:": "摘要：",
    "Reasoning:": "排序理由：",
    "Ranked literature": "排序文献",
    "Run a search before reviewing results.": "请先运行检索，再查看结果。",
    "Search title, author, abstract, DOI": "搜索题名、作者、摘要、DOI",
    "shown": "已显示",
    "selected": "已选择",
    "Rank": "排名",
    "citations": "引用",
    "All scores": "全部分数",
    "Score >= 7": "分数 >= 7",
    "Score >= 8": "分数 >= 8",
    "Score >= 9": "分数 >= 9",
    "All metadata": "全部元数据",
    "Has abstract": "有摘要",
    "Has DOI": "有 DOI",
    "Has PDF": "有 PDF",
    "Sort by rank": "按排名排序",
    "Sort by score": "按分数排序",
    "Sort by citations": "按引用数排序",
    "Sort by year": "按年份排序",
    "Select all shown": "选择当前全部",
    "Clear": "清空",
    "No papers match the current filters.": "没有论文匹配当前筛选。",
    "Select paper": "选择论文",
    "Record": "记录",
    "Local history is disabled": "本地历史记录已禁用",
    "Loading saved runs.": "正在加载保存的运行。",
    "Loading saved runs...": "正在加载保存的运行...",
    "No saved search runs yet.": "还没有保存的检索运行。",
    "Local search records": "本地检索记录",
    "Refresh": "刷新",
    "Select a saved run to inspect query, events, and ranked papers.": "选择一个保存的运行，查看检索式、事件和排序论文。",
    "source pending": "数据源待定",
    "Final query": "最终检索式",
    "Open Results": "打开结果",
    "Delete": "删除",
    "Recent log events": "最近日志事件",
    "No event log was saved for this run.": "本次运行未保存事件日志。",
    "This run did not save ranked papers.": "本次运行未保存排序论文。",
    "No citation graph nodes are available for this run.": "本次运行没有可用的引用图谱节点。",
    "Citation expansion": "引用扩展",
    "INITIAL CANDIDATES": "初始候选",
    "SEED PAPERS": "种子论文",
    "ADDED CANDIDATES": "新增候选",
    "PROMOTED RESULTS": "提升为结果",
    "FRONTIER ITEMS": "前沿任务",
    "FRONTIER REQUESTS": "前沿请求",
    "BACKWARD ADDS": "后向新增",
    "FORWARD ADDS": "前向新增",
    "Result": "结果",
    "Seed": "种子",
    "Forward citation": "前向引用",
    "Backward reference": "后向参考文献",
    "Reset": "重置",
    "All seeds": "全部种子",
    "Seed papers": "种子论文",
    "Select a node to inspect its metadata.": "选择一个节点以查看元数据。",
    "No seed papers were recorded.": "没有记录种子论文。",
    "Run an OpenAlex search with citation expansion enabled before exploring citations.": "请先运行启用引用扩展的 OpenAlex 检索，再查看引用图谱。",
    "Citation expansion was disabled for this run.": "本次运行未启用引用扩展。",
    "Citation traversal is currently available for OpenAlex runs only.": "引用遍历目前仅适用于 OpenAlex 运行。",
    "Score:": "分数：",
    "Rank:": "排名：",
    "Open record": "打开记录",
    "Record": "记录",
    "PDF": "PDF",
    "Submitting request to local backend.": "正在向本地后端提交请求。",
    "Search stopped by user.": "检索已由用户停止。",
    "Stop requested.": "已请求停止。",
    "Unknown error": "未知错误",
    "Ready. Keys and endpoint settings are held only in this browser session.": "就绪。Key 和端点设置仅保存在本次浏览器会话中。",
    "Optional for local Ollama": "本地 Ollama 可选",
    "Embedding and reranking": "向量召回与重排",
    "Embedding Provider": "Embedding 服务商",
    "Embedding Model": "Embedding 模型",
    "Embedding Base URL": "Embedding Base URL",
    "Embedding API Key": "Embedding API Key",
    "Reranker Provider": "重排服务商",
    "Reranker Model": "重排模型",
    "Reranker Base URL": "重排 Base URL",
    "Reranker API Key": "重排 API Key",
    "Local Python": "本地 Python",
    "Alibaba Cloud Bailian": "阿里云百炼",
    "Volcano Ark": "火山方舟",
    "Off": "关闭",
    "Local Python when empty": "留空时使用本地 Python",
    "Provider default": "服务商默认地址",
    "Optional; defaults to Model API key": "可选；默认复用模型 API Key",
    "Optional": "可选",
    "Configured via environment": "已通过环境变量配置",
    "Core concepts": "核心概念",
    "Question type": "问题类型",
    "Full intent analysis": "完整意图分析",
    "Likely synonyms": "可能的同义表达",
    "Adjacent concepts": "相邻概念",
    "Boundaries": "检索边界",
    "Ambiguities": "待澄清歧义",
    "Adjustment strategy": "调整策略",
    "Query views": "查询视角",
    "Query portfolio": "补充查询视角",
    "Technical audit": "技术审计",
    "Recovery and candidate audit": "恢复与候选审计",
    "Recovered issue": "已恢复问题",
    "Recovered issues": "已恢复问题",
    "Current operation": "当前操作",
    "View stage details": "展开阶段详情",
    "Hide stage details": "收起阶段详情",
    "View details": "展开详情",
    "Hide details": "收起详情",
    "No structured intent details available.": "暂无结构化意图详情。",
    "No query portfolio views were executed.": "本次未执行补充查询视角。",
  },
};

const runtimeTranslations = {
  zh: {
    exact: {
      "Interpreted intent": "意图识别结果",
      "Waiting for ranking progress.": "等待排序进度。",
      "Ranking step": "排序步骤",
      "progress": "进度",
      "Preparing LLM candidate list": "准备 LLM 候选池",
      "Abstract enrichment": "摘要补全",
      "Multi-lane retrieval": "多路召回",
      "Embedding similarity": "向量相似度",
      "RRF fusion": "RRF 融合重排",
      "External reranker": "外部重排模型",
      "Citation seed ranking": "引用扩展种子选择",
      "Citation seed selection": "引用扩展种子选择",
      "Citation expansion": "引用扩展",
      "Citation-aware candidate fusion": "引用扩展候选重融合",
      "LLM reranking": "LLM 重排序",
      "Result ranking": "结果排序",
      "Fetching missing abstracts when available.": "正在尽可能补全缺失摘要。",
      "Abstract enrichment completed.": "摘要补全已完成。",
      "No retrieval lanes returned candidates; using the primary source response.": "多路召回未返回候选，使用主数据源返回结果。",
      "External embedding completed.": "外部向量服务已完成。",
      "Using local sparse hashing similarity.": "正在使用本地稀疏哈希相似度。",
      "ModelScope API-Inference does not support rerank; keeping RRF order.": "ModelScope API-Inference 不支持重排，保留 RRF 顺序。",
      "Reranker API key or base URL is missing; keeping RRF order.": "重排 API Key 或 Base URL 缺失，保留 RRF 顺序。",
      "All configured reranker models failed; keeping RRF order.": "已配置的重排模型全部失败，保留 RRF 顺序。",
      "Ranking initial candidates to choose citation expansion seeds.": "正在排序初始候选，以选择引用扩展种子论文。",
      "Seed ranking completed.": "种子论文排序已完成。",
      "No seed papers were available for citation traversal.": "没有可用于引用遍历的种子论文。",
      "No count": "无计数",
      "Adjustment rationale": "调整依据",
      "Next query": "下一轮检索式",
      "No records found; generated a broader query.": "未找到记录；已生成更宽的检索式。",
      "No records found before the iteration limit was reached.": "达到迭代上限前仍未找到记录。",
      "Converted the generated query to the stable WoS Starter subset before calling the API.": "调用 API 前已将检索式转换为稳定的 WoS Starter 子集。",
      "WoS returned HTTP 512; rewrote the query into a simpler supported form and retried.": "WoS 返回 HTTP 512；已将检索式改写为更简单的受支持形式并重试。",
      "WoS rejected the query syntax; generated a broader replacement query.": "WoS 拒绝了检索式语法；已生成更宽的替代检索式。",
      "Candidate ledger": "候选账本",
      "Ledger details retained": "保留的账本明细",
      "Uncertain candidates": "待定候选",
      "Selected for LLM": "送入 LLM",
      "Final output candidates": "最终输出候选",
      "Truncated before LLM": "LLM 前截断",
      "Search loop audit": "检索循环审计",
      "Ranking recovery audit": "排序恢复审计",
      "Source recovery": "数据源恢复",
      "Ranking recovery": "排序恢复",
      "Citation recovery": "引用扩展恢复",
      "Citation frontier": "引用前沿",
      "Frontier stop reason": "前沿停止原因",
      "Loop decisions": "循环决策",
      "Candidate queue": "候选队列",
      "Duplicate candidates": "重复候选",
    },
    status: {
      processing: "处理中",
      complete: "已完成",
      skipped: "已跳过",
      error: "错误",
    },
    action: {
      sanitize: "清洗",
      repair: "修复",
      simplify: "简化",
      broaden: "放宽",
      narrow: "收窄",
      accept: "接受",
      accept_low: "接受偏少结果",
      accept_high: "有界接受宽结果",
      accept_pool: "接受候选池",
      empty: "无结果",
      selected_for_llm: "送入 LLM",
      truncated_before_llm: "LLM 前截断",
      llm_scored: "LLM 已评分",
      final_output: "最终输出",
      completed: "完成",
      complete: "完成",
      portfolio: "补充视角",
      selected: "已选择",
      reserve: "候补",
      skipped_budget: "预算跳过",
      skipped_duplicate: "重复跳过",
      failed: "失败",
      low_yield: "低收益停止",
      max_records: "达到候选上限",
      request_budget: "达到请求预算",
    },
    lane: {
      relevance: "相关性",
      semantic: "语义",
      impact: "影响力",
      recent: "近期文献",
      local_quality: "本地质量",
      citation_expansion: "引用扩展",
    },
  },
};

const providerDefaults = {
  openai: { model: "gpt-5.4-mini", apiType: "openai_responses", baseUrl: "https://api.openai.com/v1" },
  anthropic: { model: "claude-sonnet-4-6", apiType: "anthropic_messages", baseUrl: "https://api.anthropic.com" },
  google: { model: "gemini-3.5-flash", apiType: "openai_chat", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai" },
  deepseek: { model: "deepseek-v4-flash", apiType: "openai_chat", baseUrl: "https://api.deepseek.com" },
  cstcloud: { model: "deepseek-v4-flash", apiType: "openai_chat", baseUrl: "https://uni-api.cstcloud.cn/v1" },
  dashscope: { model: "qwen3.6-plus", apiType: "openai_chat", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  moonshot: { model: "kimi-k2.6", apiType: "openai_chat", baseUrl: "https://api.moonshot.ai/v1" },
  zhipu: { model: "glm-5.1", apiType: "openai_chat", baseUrl: "https://open.bigmodel.cn/api/paas/v4" },
  siliconflow: { model: "deepseek-ai/DeepSeek-V4-Flash", apiType: "openai_chat", baseUrl: "https://api.siliconflow.cn/v1" },
  openrouter: { model: "openai/gpt-5.4-mini", apiType: "openai_chat", baseUrl: "https://openrouter.ai/api/v1" },
  nvidia: { model: "nvidia/llama-3.3-nemotron-super-49b-v1.5", apiType: "openai_chat", baseUrl: "https://integrate.api.nvidia.com/v1" },
  volcengine: { model: "doubao-seed-2-0-mini-260428", apiType: "openai_chat", baseUrl: "https://ark.cn-beijing.volces.com/api/v3" },
  hunyuan: { model: "hunyuan-turbos-latest", apiType: "openai_chat", baseUrl: "https://tokenhub.tencentmaas.com/v1" },
  qianfan: { model: "ernie-5.0", apiType: "openai_chat", baseUrl: "https://qianfan.baidubce.com/v2" },
  modelscope: { model: "Qwen/Qwen3-235B-A22B-Instruct-2507", apiType: "openai_chat", baseUrl: "https://api-inference.modelscope.cn/v1" },
  ollama: { model: "qwen3:8b", apiType: "openai_chat", baseUrl: "http://127.0.0.1:11434/v1" },
  custom: { model: "", apiType: "openai_chat", baseUrl: "" },
};

const retrievalProviderDefaults = {
  local: { embeddingModel: "", rerankerModel: "", baseUrl: "" },
  cstcloud: {
    embeddingModel: "qwen3-embedding:8b,bge-large-zh:latest",
    rerankerModel: "qwen3-reranker:8b",
    baseUrl: "https://uni-api.cstcloud.cn/v1",
  },
  openai: { embeddingModel: "text-embedding-3-large", rerankerModel: "", baseUrl: "https://api.openai.com/v1" },
  dashscope: { embeddingModel: "text-embedding-v4", rerankerModel: "", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  siliconflow: { embeddingModel: "BAAI/bge-large-zh-v1.5", rerankerModel: "BAAI/bge-reranker-v2-m3", baseUrl: "https://api.siliconflow.cn/v1" },
  openrouter: {
    embeddingModel: "openai/text-embedding-3-small",
    rerankerModel: "jinaai/jina-reranker-v2-base-multilingual",
    baseUrl: "https://openrouter.ai/api/v1",
  },
  nvidia: {
    embeddingModel: "nvidia/nv-embedqa-e5-v5",
    rerankerModel: "nv-rerank-qa-mistral-4b:1",
    embeddingBaseUrl: "https://integrate.api.nvidia.com/v1",
    rerankerBaseUrl: "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking",
    baseUrl: "https://integrate.api.nvidia.com/v1",
  },
  zhipu: { embeddingModel: "embedding-3", rerankerModel: "", baseUrl: "https://open.bigmodel.cn/api/paas/v4" },
  volcengine: { embeddingModel: "", rerankerModel: "", baseUrl: "https://ark.cn-beijing.volces.com/api/v3" },
  modelscope: { embeddingModel: "Qwen/Qwen3-Embedding-8B,Qwen/Qwen3-Embedding-4B", rerankerModel: "", baseUrl: "https://api-inference.modelscope.cn/v1" },
  custom: { embeddingModel: "", rerankerModel: "", baseUrl: "" },
};

const stageOrder = ["query", "search", "ranking", "results"];
const sourceLabels = {
  openalex: "OpenAlex (precise search)",
  arxiv: "arXiv (preprints)",
  semanticscholar: "Semantic Scholar (broad scholarly graph)",
  pubmed: "PubMed (biomedical literature)",
  googlescholar: "Google Scholar (via Serper)",
  paperhub: "Computer science top conferences",
  crossref: "Crossref (metadata / DOI registry)",
  wos: "Web of Science Starter (temporarily unavailable)",
};
const compactSourceLabels = {
  openalex: "OpenAlex",
  arxiv: "arXiv",
  semanticscholar: "Semantic Scholar",
  pubmed: "PubMed",
  googlescholar: "Google Scholar",
  paperhub: "CS top conferences",
  crossref: "Crossref",
  wos: "Web of Science Starter",
};
const sourceMetaLabels = {
  openalex: "Optional OpenAlex API key and email are in Advanced settings.",
  arxiv: "arXiv does not require an API key.",
  semanticscholar: "Semantic Scholar API key is optional in Advanced settings.",
  pubmed: "PubMed API key and email are optional in Advanced settings.",
  googlescholar: "Google Scholar requires a Serper API key in Advanced settings.",
  paperhub: "Computer science top-conference search needs no key.",
  crossref: "Crossref email is optional but recommended in Advanced settings.",
  wos: "WoS requires an API key in Advanced settings.",
};
const searchBudgetHelpText = {
  fast: "Fewest requests for faster searches.",
  medium: "Balanced recall, ranking depth, and API use. Recommended.",
  high: "Wider recall and deeper citation traversal; takes longer.",
  max: "Largest candidate and ranking budget; intended for difficult searches.",
};

let activeLanguage = loadLanguage();
let workflowState = createWorkflowState();
let disclosureState = createDisclosureState();
let logPanelExpanded = false;
let logHasError = false;
let latestPayload = null;
let latestResult = null;
let latestError = "";
let activeView = "search";
let selectedPaperIds = new Set();
let resultFilters = {
  query: "",
  minScore: "all",
  availability: "all",
  sort: "rank",
};
let selectedCitationNodeId = "";
let resultSearchTimer = null;
let citationGraphState = createCitationGraphState();
let historyRuns = [];
let historyDetail = null;
let historyStatus = { enabled: true, path: "" };
let historyLoading = false;
let historyError = "";
let activeSearchController = null;
let activeSearchToken = 0;
let activeBackendRunId = "";
let pendingResumeRunId = "";
let latestStreamHeartbeatLogAt = 0;
let disciplineOptions = [];
let sourceFilterDefinitions = {};
let environmentConfig = {
  has_llm_api_key: false,
  has_wos_api_key: false,
  has_semantic_scholar_api_key: false,
  has_pubmed_api_key: false,
  has_pubmed_email: false,
  has_serper_api_key: false,
  llm_provider: "",
};

function loadLanguage() {
  const saved = window.localStorage ? window.localStorage.getItem(languageStorageKey) : "";
  return saved === "zh" ? "zh" : "en";
}

function translatedText(text) {
  const value = String(text ?? "");
  if (activeLanguage !== "zh") {
    return value;
  }
  return translations.zh[value] || value;
}

function localizedText(englishText, chineseText) {
  return activeLanguage === "zh" ? chineseText : englishText;
}

function translatedRuntimeText(text) {
  const value = String(text ?? "");
  if (activeLanguage !== "zh" || !value) {
    return value;
  }
  const zh = runtimeTranslations.zh;
  if (zh.exact[value]) {
    return zh.exact[value];
  }
  const patterns = [
    [/^(\d+) fused candidates before citation expansion\.$/, (_, count) => `${count} 个融合候选进入引用扩展前准备。`],
    [/^(\d+) candidates ready before LLM ranking\.$/, (_, count) => `${count} 个候选已准备进入 LLM 重排序。`],
    [/^Starting (.+) lanes; lane limit (\d+)\.$/, (_, lanes, limit) => `启动 ${translatedLaneList(lanes)} 多路召回；单路上限 ${limit}。`],
    [/^(.+) lane finished; collected (\d+) lane candidates\.$/, (_, lane, count) => `${translatedLaneName(lane)}召回完成；已收集 ${count} 个分路候选。`],
    [/^Computing semantic similarity for (\d+) unique candidates\.$/, (_, count) => `正在为 ${count} 个去重候选计算语义相似度。`],
    [/^Fusing lane rank, BM25\/term coverage, and embedding signals for (\d+) candidates\.$/, (_, count) => `正在融合分路排名、BM25/词项覆盖和向量信号，共 ${count} 个候选。`],
    [/^Fused (\d+) unique candidates into a pool of (\d+)\.$/, (_, total, kept) => `已将 ${total} 个去重候选融合为 ${kept} 个候选池结果。`],
    [/^Retrieval completed with (\d+) fused candidates\.$/, (_, count) => `多路召回完成，得到 ${count} 个融合候选。`],
    [/^Calling (.+) reranker for the top (\d+) candidates\.$/, (_, provider, count) => `正在调用 ${provider} 重排模型处理前 ${count} 个候选。`],
    [/^(.+) reranker completed with model=(.+)\.$/, (_, provider, model) => `${provider} 重排模型已完成；模型=${model}。`],
    [/^Traversing references and citing works for (\d+) seed papers\.$/, (_, count) => `正在遍历 ${count} 篇种子论文的参考文献和施引文献。`],
    [/^Citation traversal failed: (.+)$/, (_, reason) => `引用遍历失败：${reason}`],
    [/^Added (\d+) citation-neighbor candidates; candidate pool=(\d+)\.$/, (_, added, total) => `新增 ${added} 个引用邻近候选；候选池共 ${total} 个。`],
    [/^Re-ranking the complete candidate pool after citation expansion with local BM25, sparse hashing similarity, and RRF\.$/, () => "引用扩展完成后，正在使用本地 BM25、稀疏哈希相似度和 RRF 对完整候选池重新排序。"],
    [/^Re-fused (\d+) candidates after citation expansion; citation candidates=(\d+)\.$/, (_, total, citations) => `引用扩展后已重新融合 ${total} 个候选，其中引用候选 ${citations} 个。`],
    [/^Query view (.+) completed; returned (\d+) and added (\d+) unique candidates\.$/, (_, view, returned, added) => `查询视图 ${view} 已完成；返回 ${returned} 条并新增 ${added} 个去重候选。`],
    [/^Query view (.+) skipped_budget; returned (\d+) and added (\d+) unique candidates\.$/, (_, view) => `查询视图 ${view} 因达到请求预算而保留未执行。`],
    [/^Query view (.+) skipped_duplicate; returned (\d+) and added (\d+) unique candidates\.$/, (_, view) => `查询视图 ${view} 与已执行检索式重复，已跳过。`],
    [/^Scoring (\d+) candidates in one LLM batch\.$/, (_, count) => `正在用 1 个 LLM 批次为 ${count} 个候选评分。`],
    [/^Scored (\d+) candidates\.$/, (_, count) => `已为 ${count} 个候选评分。`],
    [/^Scoring (\d+) candidates in (\d+) LLM batches; concurrency=(\d+)\.$/, (_, count, batches, concurrency) => `正在用 ${batches} 个 LLM 批次为 ${count} 个候选评分；并发=${concurrency}。`],
    [/^Batch (\d+)\/(\d+) failed at concurrency=(\d+); retrying failed batches with lower concurrency\.$/, (_, index, total, concurrency) => `第 ${index}/${total} 批在并发 ${concurrency} 下失败；将降低并发重试失败批次。`],
    [/^Completed batch (\d+)\/(\d+) at concurrency=(\d+)\.$/, (_, index, total, concurrency) => `第 ${index}/${total} 批已完成；并发=${concurrency}。`],
    [/^(\d+) batch\(es\), (\d+) candidates, failed even at concurrency=4\.$/, (_, batches, count) => `${batches} 个批次、${count} 个候选在最低并发 4 下仍失败。`],
    [/^LLM scoring completed for (\d+)\/(\d+) batches\.$/, (_, done, total) => `LLM 评分已完成 ${done}/${total} 个批次。`],
    [/^(\d+) records found, above the target maximum of (\d+); generated a narrower query\.$/, (_, count, target) => `找到 ${count} 条记录，高于目标上限 ${target}；已生成更窄的检索式。`],
    [/^Only (\d+) records found, below the target minimum of (\d+); generated a broader query\.$/, (_, count, target) => `仅找到 ${count} 条记录，低于目标下限 ${target}；已生成更宽的检索式。`],
    [/^Accepted (\d+) records within the target range\.$/, (_, count) => `接受 ${count} 条记录，数量位于目标范围内。`],
    [/^Accepted (\d+) records at the iteration limit, above the target maximum of (\d+)\.$/, (_, count, target) => `达到迭代上限后接受 ${count} 条记录，仍高于目标上限 ${target}。`],
    [/^Accepted (\d+) records at the iteration limit, below the target minimum of (\d+)\.$/, (_, count, target) => `达到迭代上限后接受 ${count} 条记录，仍低于目标下限 ${target}。`],
    [/^(\d+) records found, above the LLM pre-ranking safety pool of (\d+); generated a narrower query\.$/, (_, count, limit) => `找到 ${count} 条记录，高于 LLM 预排序安全候选池上限 ${limit}；已生成更窄的检索式。`],
    [/^Accepted (\d+) records at the iteration limit, above the LLM pre-ranking safety pool of (\d+); the fused candidate pool will be truncated before LLM ranking\.$/, (_, count, limit) => `达到迭代上限后接受 ${count} 条记录，高于 LLM 预排序安全候选池上限 ${limit}；融合候选池会在 LLM 排序前截断。`],
    [/^(.+) rejected the query; repaired the source syntax and retried\.$/, (_, source) => `${source} 拒绝了检索式；已修复数据源语法并重试。`],
    [/^Sanitized the generated (.+) query before calling the API\.$/, (_, source) => `调用 API 前已清洗 ${source} 检索式。`],
  ];
  for (const [pattern, replacement] of patterns) {
    const match = value.match(pattern);
    if (match) {
      return replacement(...match);
    }
  }
  return translatedText(value);
}

function translatedLaneName(value) {
  const text = String(value || "").trim();
  if (activeLanguage !== "zh") {
    return text;
  }
  return runtimeTranslations.zh.lane[text] || text;
}

function translatedLaneList(value) {
  return String(value || "")
    .split(",")
    .map((lane) => lane.trim())
    .filter(Boolean)
    .map(translatedLaneName)
    .join(activeLanguage === "zh" ? "、" : ", ");
}

function translatedActionText(value) {
  const text = String(value || "");
  if (activeLanguage !== "zh") {
    return text === "accept_high" ? "accept bounded broad pool" : text;
  }
  return runtimeTranslations.zh.action[text] || translatedRuntimeText(text);
}

function translatedStatusText(value) {
  const text = String(value || "processing").toLowerCase();
  if (activeLanguage !== "zh") {
    return text.toUpperCase();
  }
  return runtimeTranslations.zh.status[text] || translatedRuntimeText(text);
}

function translateWithWhitespace(value) {
  const text = String(value ?? "");
  const match = text.match(/^(\s*)(.*?)(\s*)$/s);
  if (!match) {
    return translatedText(text);
  }
  return `${match[1]}${translatedText(match[2])}${match[3]}`;
}

function setTranslatedText(node, englishText) {
  if (!node) {
    return;
  }
  node.dataset.i18nText = englishText;
  node.textContent = translatedText(englishText);
}

function translatedAttrName(attribute) {
  return `data-i18n-${attribute}-original`;
}

function setTranslatedAttribute(node, attribute, englishText) {
  if (!node) {
    return;
  }
  node.setAttribute(translatedAttrName(attribute), englishText);
  node.setAttribute(attribute, translatedText(englishText));
}

function shouldSkipTranslationNode(node) {
  const parent = node.parentElement;
  return !parent || Boolean(parent.closest("script, style, pre, code, textarea, [data-no-i18n], [data-i18n-text]"));
}

function applyLanguage(root = document.body) {
  if (!root) {
    return;
  }
  document.documentElement.lang = activeLanguage === "zh" ? "zh-CN" : "en";
  document.body.dataset.uiLanguage = activeLanguage;
  languageButtons.forEach((button) => {
    const active = button.dataset.language === activeLanguage;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });

  const elementRoot = root.nodeType === Node.ELEMENT_NODE ? root : document.body;
  const dynamicElements = [];
  if (elementRoot.matches && elementRoot.matches("[data-i18n-text]")) {
    dynamicElements.push(elementRoot);
  }
  if (elementRoot.querySelectorAll) {
    dynamicElements.push(...elementRoot.querySelectorAll("[data-i18n-text]"));
  }
  dynamicElements.forEach((node) => {
    node.textContent = translatedText(node.dataset.i18nText || "");
  });

  const attributes = ["placeholder", "title", "aria-label"];
  const attrElements = elementRoot.querySelectorAll ? [elementRoot, ...elementRoot.querySelectorAll("*")] : [];
  attrElements.forEach((node) => {
    attributes.forEach((attribute) => {
      if (!node.hasAttribute || !node.hasAttribute(attribute)) {
        return;
      }
      const originalName = translatedAttrName(attribute);
      if (!node.hasAttribute(originalName)) {
        node.setAttribute(originalName, node.getAttribute(attribute));
      }
      node.setAttribute(attribute, translatedText(node.getAttribute(originalName)));
    });
  });

  const walkerRoot = root.nodeType === Node.TEXT_NODE ? root.parentNode : root;
  if (!walkerRoot) {
    return;
  }
  const walker = document.createTreeWalker(walkerRoot, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (shouldSkipTranslationNode(node) || !node.nodeValue.trim()) {
      continue;
    }
    if (!node.__paperseekI18nOriginal) {
      node.__paperseekI18nOriginal = node.nodeValue;
    }
    node.nodeValue = translateWithWhitespace(node.__paperseekI18nOriginal);
  }
}

function setLanguage(language) {
  activeLanguage = language === "zh" ? "zh" : "en";
  if (window.localStorage) {
    window.localStorage.setItem(languageStorageKey, activeLanguage);
  }
  updateSourceSummary();
  updateCredentialPlaceholders();
  updateDisciplineSummary();
  updateSearchBudgetHelp();
  renderWorkflow();
  applyLanguage();
}

function selectedSearchBudget() {
  const selected = searchBudgetInputs.find((input) => input.checked);
  return selected ? selected.value : "fast";
}

function setSearchBudget(value) {
  const normalized = ["fast", "medium", "high", "max"].includes(String(value || "").toLowerCase())
    ? String(value).toLowerCase()
    : "fast";
  searchBudgetInputs.forEach((input) => {
    input.checked = input.value === normalized;
  });
  updateSearchBudgetHelp();
}

function updateSearchBudgetHelp() {
  setTranslatedText(searchBudgetHelp, searchBudgetHelpText[selectedSearchBudget()] || searchBudgetHelpText.fast);
}

function initLanguageControls() {
  languageButtons.forEach((button) => {
    button.addEventListener("click", () => setLanguage(button.dataset.language));
  });
  applyLanguage();
}

const fallbackTimeZone = "Asia/Shanghai";
const clientTimeZone = detectClientTimeZone();

function detectClientTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || fallbackTimeZone;
  } catch (_) {
    return fallbackTimeZone;
  }
}

function clientUtcOffsetMinutes() {
  if (clientTimeZone === fallbackTimeZone) {
    return 8 * 60;
  }
  try {
    return -new Date().getTimezoneOffset();
  } catch (_) {
    return 8 * 60;
  }
}

function zonedDateParts(date = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: clientTimeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).formatToParts(date);
    return Object.fromEntries(parts.map((part) => [part.type, part.value]));
  } catch (_) {
    const fallback = new Date(date.getTime() + 8 * 60 * 60 * 1000);
    return {
      year: String(fallback.getUTCFullYear()),
      month: String(fallback.getUTCMonth() + 1).padStart(2, "0"),
      day: String(fallback.getUTCDate()).padStart(2, "0"),
      hour: String(fallback.getUTCHours()).padStart(2, "0"),
      minute: String(fallback.getUTCMinutes()).padStart(2, "0"),
      second: String(fallback.getUTCSeconds()).padStart(2, "0"),
    };
  }
}

function nowStamp() {
  const parts = zonedDateParts();
  return `${parts.hour}:${parts.minute}:${parts.second}`;
}

function dateStamp() {
  const parts = zonedDateParts();
  return `${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}`;
}

function log(message) {
  logOutput.textContent += `${nowStamp()}  ${message}\n`;
  logOutput.scrollTop = logOutput.scrollHeight;
  updateExportButtons();
}

function renderLogPanelState() {
  if (!logPanel || !rightPane || !logToggle) {
    return;
  }
  logPanel.classList.toggle("is-collapsed", !logPanelExpanded);
  rightPane.classList.toggle("log-collapsed", !logPanelExpanded);
  logToggle.setAttribute("aria-expanded", logPanelExpanded ? "true" : "false");
  setTranslatedAttribute(logToggle, "aria-label", logPanelExpanded ? "Collapse system log" : "Expand system log");
  if (logErrorBadge) {
    logErrorBadge.classList.toggle("is-hidden", !logHasError);
  }
}

function setLogPanelExpanded(expanded, { error = false } = {}) {
  logPanelExpanded = Boolean(expanded);
  if (error) {
    logHasError = true;
  }
  renderLogPanelState();
  if (logPanelExpanded && logOutput) {
    requestAnimationFrame(() => {
      logOutput.scrollTop = logOutput.scrollHeight;
    });
  }
}

function resetLogPanel() {
  logPanelExpanded = false;
  logHasError = false;
  renderLogPanelState();
}

function setBusy(isBusy) {
  searchButton.disabled = isBusy;
  checkConfigButton.disabled = isBusy;
  if (stopButton) {
    stopButton.disabled = !isBusy;
  }
  setTranslatedText(searchButton.querySelector("span"), isBusy ? "Searching" : "Run Search");
  if (isBusy) {
    setTranslatedText(stateLabel, "Processing");
  } else if (!["Error", "Stopped"].includes(stateLabel.dataset.i18nText || stateLabel.textContent)) {
    setTranslatedText(stateLabel, "Ready");
  }
  document.body.classList.toggle("is-busy", isBusy);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getValue(id) {
  return document.getElementById(id).value.trim();
}

function getNumber(id) {
  return Number(document.getElementById(id).value);
}

function updateSourceSummary() {
  const source = dataSourceSelect.value || "openalex";
  if (basicSourceName) {
    setTranslatedText(basicSourceName, compactSourceLabels[source] || source.toUpperCase());
  }
  if (basicSourceMeta) {
    setTranslatedText(basicSourceMeta, sourceMetaLabels[source] || "Source details are in Advanced settings.");
  }
}

function activeSourceFilterDefinition() {
  const source = dataSourceSelect.value || "openalex";
  return sourceFilterDefinitions[source] || {
    mode: "native",
    label: "OpenAlex Field",
    options: disciplineOptions,
  };
}

function selectedDisciplineFields() {
  if (activeSourceFilterDefinition().mode !== "native") {
    return [];
  }
  if (!disciplineOptionsContainer) {
    return [];
  }
  return [...disciplineOptionsContainer.querySelectorAll("input[type='checkbox']:checked")].map((item) => item.value);
}

function updateDisciplineSummary() {
  if (!disciplineSummary) {
    return;
  }
  const selected = selectedDisciplineFields();
  if (!selected.length) {
    setTranslatedText(disciplineSummary, "Any filter");
    return;
  }
  const labels = selected.map((id) => {
    const option = disciplineOptions.find((item) => String(item.id) === String(id));
    return option ? option.label : id;
  });
  const text = labels.length > 2 ? `${labels.slice(0, 2).join(", ")} +${labels.length - 2}` : labels.join(", ");
  disciplineSummary.dataset.i18nText = "";
  disciplineSummary.textContent = text;
}

function setSelectedDisciplineFields(values = []) {
  const selected = new Set((values || []).map((value) => String(value)));
  if (!disciplineOptionsContainer) {
    return;
  }
  disciplineOptionsContainer.querySelectorAll("input[type='checkbox']").forEach((input) => {
    input.checked = selected.has(String(input.value));
  });
  updateDisciplineSummary();
}

function updateSourceFilterUi({ reset = false } = {}) {
  const definition = activeSourceFilterDefinition();
  const mode = definition.mode || "text";
  if (disciplinePickerLabel) {
    setTranslatedText(disciplinePickerLabel, definition.label || "Source Filter");
  }
  if (fieldHintLabel) {
    setTranslatedText(fieldHintLabel, definition.label || "Field/context hint");
  }
  if (reset) {
    setSelectedDisciplineFields([]);
  }
  if (mode === "native" && Array.isArray(definition.options) && definition.options.length) {
    disciplineOptions = definition.options;
    if (disciplinePicker) {
      disciplinePicker.classList.remove("is-hidden");
    }
    if (fieldHintField) {
      fieldHintField.classList.add("is-hidden");
    }
    renderDisciplineOptions();
    return;
  }
  disciplineOptions = [];
  if (disciplinePicker) {
    disciplinePicker.classList.add("is-hidden");
    disciplinePicker.open = false;
  }
  if (fieldHintField) {
    fieldHintField.classList.remove("is-hidden");
  }
}

function renderDisciplineOptions() {
  if (!disciplineOptionsContainer) {
    return;
  }
  disciplineOptionsContainer.textContent = "";
  if (!disciplineOptions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-mini";
    setTranslatedText(empty, "Discipline fields unavailable");
    disciplineOptionsContainer.appendChild(empty);
    updateDisciplineSummary();
    return;
  }
  const domains = new Map();
  disciplineOptions.forEach((option) => {
    const domain = option.domain || "Other";
    if (!domains.has(domain)) {
      domains.set(domain, []);
    }
    domains.get(domain).push(option);
  });
  domains.forEach((options, domain) => {
    const group = document.createElement("div");
    group.className = "discipline-domain";
    const title = document.createElement("div");
    title.className = "discipline-domain-title";
    title.textContent = domain;
    group.appendChild(title);
    options.forEach((option) => {
      const label = document.createElement("label");
      label.className = "discipline-option";
      label.dataset.noI18n = "true";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = String(option.id);
      const text = document.createElement("span");
      text.textContent = option.label;
      label.append(input, text);
      group.appendChild(label);
    });
    disciplineOptionsContainer.appendChild(group);
  });
  updateDisciplineSummary();
}

async function loadDisciplineOptions() {
  if (!disciplineOptionsContainer) {
    return;
  }
  const loading = document.createElement("div");
  loading.className = "empty-mini";
  setTranslatedText(loading, "Loading discipline fields...");
  disciplineOptionsContainer.textContent = "";
  disciplineOptionsContainer.appendChild(loading);
  try {
    const response = await fetch("/api/disciplines");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    disciplineOptions = Array.isArray(data.disciplines) ? data.disciplines : [];
    sourceFilterDefinitions = data.sources || {
      openalex: { mode: "native", label: "OpenAlex Field", options: disciplineOptions },
    };
  } catch (_) {
    disciplineOptions = [];
    sourceFilterDefinitions = {};
  }
  updateSourceFilterUi();
}

function envLlmKeyApplies(provider = providerSelect.value) {
  return Boolean(environmentConfig.has_llm_api_key && (!environmentConfig.llm_provider || environmentConfig.llm_provider === provider));
}

function updateCredentialPlaceholders() {
  const llmKeyInput = document.getElementById("llmApiKey");
  const wosKeyInput = document.getElementById("wosApiKey");
  const openAlexKeyInput = document.getElementById("openAlexApiKey");
  const semanticScholarKeyInput = document.getElementById("semanticScholarApiKey");
  const pubmedKeyInput = document.getElementById("pubmedApiKey");
  const pubmedEmailInput = document.getElementById("pubmedEmail");
  const serperKeyInput = document.getElementById("serperApiKey");
  if (llmKeyInput) {
    if (providerSelect.value === "ollama") {
      setTranslatedAttribute(llmKeyInput, "placeholder", "Optional for local Ollama");
    } else if (envLlmKeyApplies(providerSelect.value)) {
      setTranslatedAttribute(llmKeyInput, "placeholder", "Configured via environment");
    } else {
      setTranslatedAttribute(llmKeyInput, "placeholder", "");
    }
  }
  if (wosKeyInput && environmentConfig.has_wos_api_key) {
    setTranslatedAttribute(wosKeyInput, "placeholder", "Configured via environment");
  }
  if (openAlexKeyInput && environmentConfig.has_openalex_api_key) {
    setTranslatedAttribute(openAlexKeyInput, "placeholder", "Configured via environment");
  }
  if (semanticScholarKeyInput && environmentConfig.has_semantic_scholar_api_key) {
    setTranslatedAttribute(semanticScholarKeyInput, "placeholder", "Configured via environment");
  }
  if (pubmedKeyInput && environmentConfig.has_pubmed_api_key) {
    setTranslatedAttribute(pubmedKeyInput, "placeholder", "Configured via environment");
  }
  if (pubmedEmailInput && environmentConfig.has_pubmed_email) {
    setTranslatedAttribute(pubmedEmailInput, "placeholder", "Configured via environment");
  }
  if (serperKeyInput && environmentConfig.has_serper_api_key) {
    setTranslatedAttribute(serperKeyInput, "placeholder", "Configured via environment");
  }
}

async function loadServerDefaults() {
  try {
    const response = await fetch("/api/config/defaults");
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    environmentConfig = { ...environmentConfig, ...data };
    if (data.data_source) {
      dataSourceSelect.value = data.data_source;
    }
    setSearchBudget(data.search_budget || "fast");
    if (data.llm_provider && providerDefaults[data.llm_provider]) {
      providerSelect.value = data.llm_provider;
    }
    if (data.llm_api_type) {
      apiTypeSelect.value = data.llm_api_type;
    }
    if (data.llm_model) {
      modelInput.value = data.llm_model;
    }
    if (data.llm_base_url) {
      baseUrlInput.value = data.llm_base_url;
    }
    if (Number.isFinite(Number(data.target_min))) {
      document.getElementById("targetMin").value = Number(data.target_min);
    }
    if (Number.isFinite(Number(data.target_max))) {
      document.getElementById("targetMax").value = Number(data.target_max);
    }
    if (Array.isArray(data.discipline_fields)) {
      setSelectedDisciplineFields(data.discipline_fields);
    }
    document.getElementById("fetchAbstracts").checked = Boolean(data.fetch_abstracts);
    document.getElementById("expandCitations").checked = Boolean(data.expand_citations);
    updateSourceFields();
    updateCredentialPlaceholders();
    updateSourceSummary();
  } catch (_) {
    updateCredentialPlaceholders();
    updateSourceSummary();
  }
}

function createCitationGraphState() {
  return {
    scale: 1,
    panX: 0,
    panY: 0,
    positions: {},
    draggingNodeId: "",
    panning: false,
    lastX: 0,
    lastY: 0,
    dragOffsetX: 0,
    dragOffsetY: 0,
  };
}

function paperId(paper) {
  return String(paper.uid || paper.doi || paper.title || paper.rank || "");
}

function plausiblePublishYear(value) {
  const current = new Date().getUTCFullYear() + 2;
  if (value !== null && value !== undefined && value !== "") {
    const direct = Number(value);
    if (Number.isInteger(direct) && direct >= 1500 && direct <= current) {
      return direct;
    }
  }
  const match = String(value || "").match(/\b(1[5-9]\d{2}|20\d{2})\b/);
  if (!match) {
    return "";
  }
  const year = Number(match[1]);
  return year <= current ? year : "";
}

function cleanScholarFragment(value) {
  return String(value || "")
    .replace(/\u0431\u043d/g, "...")
    .replace(/\b(1[5-9]\d{2}|20\d{2})\b/g, "")
    .replace(/\bAvailable at\s+/gi, "")
    .replace(/\bSSRN\s+\d+\b/gi, "SSRN")
    .replace(/\.\.\./g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[,;: -]+|[,;: -]+$/g, "");
}

function splitScholarSummary(value) {
  return String(value || "")
    .split(/\s+-\s+/)
    .map(cleanScholarFragment)
    .filter(Boolean);
}

function normalizeScholarPaper(paper) {
  if (!paper || paper.provider !== "googlescholar") {
    return paper;
  }
  const source = String(paper.source || paper.venue || "");
  const next = { ...paper };
  const year = plausiblePublishYear(paper.publish_year || paper.year) || plausiblePublishYear(source);
  if (year) {
    next.publish_year = year;
    next.year = year;
  }
  if (source.includes(" - ")) {
    const parts = splitScholarSummary(source);
    if ((!Array.isArray(next.authors) || next.authors.length === 0) && parts.length > 1 && !plausiblePublishYear(parts[0])) {
      next.authors = parts[0]
        .split(/\s*,\s*|;\s*/)
        .map(cleanScholarFragment)
        .filter((name) => name && !plausiblePublishYear(name) && !/:\/\/|www\.|\.(com|org|net|edu)\b/i.test(name));
    }
    const venue = parts.slice(1).find((part) => part && !plausiblePublishYear(part));
    if (venue) {
      next.source = venue;
      next.venue = venue;
    }
  } else if (source) {
    const cleanSource = cleanScholarFragment(source);
    if (cleanSource) {
      next.source = cleanSource;
      next.venue = cleanSource;
    }
  }
  return next;
}

function normalizePapers(papers) {
  return (papers || []).map(normalizeScholarPaper);
}

function selectedPapers() {
  const papers = latestResult && latestResult.ranked ? normalizePapers(latestResult.ranked) : [];
  return papers.filter((paper) => selectedPaperIds.has(paperId(paper)));
}

function getFilteredPapers() {
  const papers = latestResult && latestResult.ranked ? normalizePapers(latestResult.ranked) : [];
  const query = resultFilters.query.trim().toLowerCase();
  let filtered = papers.filter((paper) => {
    if (query) {
      const haystack = [
        paper.title,
        (paper.authors || []).join(" "),
        paper.abstract,
        paper.source,
        paper.doi,
        paper.keywords,
      ].join(" ").toLowerCase();
      if (!haystack.includes(query)) {
        return false;
      }
    }
    if (resultFilters.minScore !== "all" && Number(paper.score || 0) < Number(resultFilters.minScore)) {
      return false;
    }
    if (resultFilters.availability === "abstract" && !paper.abstract) {
      return false;
    }
    if (resultFilters.availability === "doi" && !paper.doi) {
      return false;
    }
    if (resultFilters.availability === "pdf" && !(paper.links && paper.links.pdf)) {
      return false;
    }
    return true;
  });

  const numeric = (value) => Number(value || 0);
  filtered.sort((a, b) => {
    if (resultFilters.sort === "score") {
      return numeric(b.score) - numeric(a.score);
    }
    if (resultFilters.sort === "citations") {
      return numeric(b.citations) - numeric(a.citations);
    }
    if (resultFilters.sort === "year") {
      return numeric(b.publish_year) - numeric(a.publish_year);
    }
    return numeric(a.rank) - numeric(b.rank);
  });
  return filtered;
}

function getExportPapers() {
  const selected = selectedPapers();
  return selected.length ? selected : getFilteredPapers();
}

function updateExportButtons() {
  if (exportLogButton) {
    exportLogButton.disabled = !logOutput.textContent.trim();
  }
  document.querySelectorAll("[data-action='export-results-csv']").forEach((button) => {
    button.disabled = getExportPapers().length === 0;
  });
}

function exportResultsCsv() {
  const filename = `${filenamePart(exportQuestionTheme())}-${dateStamp()}-papers.csv`;
  downloadText(filename, papersToCsv(getExportPapers()), "text/csv;charset=utf-8");
}

function filenamePart(value, fallback = "literature-search") {
  const text = String(value || fallback);
  const raw = (typeof text.normalize === "function" ? text.normalize("NFKC") : text).trim();
  let cleaned = "";
  try {
    const nonWord = new RegExp("[^\\p{L}\\p{N}]+", "gu");
    cleaned = raw.replace(nonWord, "-").replace(/^-+|-+$/g, "");
  } catch (_) {
    cleaned = raw
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }
  return cleaned.slice(0, 64) || fallback;
}

function exportQuestionTheme() {
  return (latestPayload && latestPayload.question) ||
    (latestResult && latestResult.question) ||
    getValue("question") ||
    "literature-search";
}

function downloadText(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function currentLogText() {
  const source = latestPayload && latestPayload.data_source ? latestPayload.data_source : "not started";
  return [
    `Exported at: ${new Date().toISOString()}`,
    `Run ID: ${runId.textContent}`,
    `Source: ${source}`,
    "",
    logOutput.textContent.trimEnd(),
    "",
  ].join("\n");
}

function csvCell(value) {
  const text = Array.isArray(value) ? value.join("; ") : String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function papersToCsv(papers) {
  const columns = [
    "rank",
    "score",
    "title",
    "authors",
    "publish_year",
    "source",
    "provider",
    "document_types",
    "citations",
    "doi",
    "keywords",
    "abstract",
    "reasoning",
    "record_url",
    "pdf_url",
  ];
  const rows = (papers || []).map((paper, index) => [
    index + 1,
    paper.score,
    paper.title,
    paper.authors || [],
    paper.publish_year,
    paper.source,
    paper.provider,
    paper.document_types || [],
    paper.citations,
    paper.doi,
    paper.keywords,
    paper.abstract,
    paper.reasoning,
    paper.links && paper.links.record,
    paper.links && paper.links.pdf,
  ].map(csvCell).join(","));
  return `\ufeff${[columns.join(","), ...rows].join("\r\n")}`;
}

function clearValidationState() {
  for (const node of document.querySelectorAll(".is-invalid")) {
    node.classList.remove("is-invalid");
  }
}

function createDisclosureState() {
  return {
    stages: { query: true, search: false, ranking: false, results: false },
    stageManual: {},
    sections: {},
  };
}

function resetDisclosureState() {
  disclosureState = createDisclosureState();
}

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object || {}, key);
}

function isSectionExpanded(key, defaultExpanded = false) {
  return hasOwn(disclosureState.sections, key) ? Boolean(disclosureState.sections[key]) : Boolean(defaultExpanded);
}

function syncStageDisclosure(stageKey, status) {
  const normalizedStatus = String(status || "").toUpperCase();
  if (normalizedStatus === "ERROR") {
    stageOrder.forEach((key) => {
      if (!hasOwn(disclosureState.stageManual, key) || key === stageKey) {
        disclosureState.stages[key] = key === stageKey;
      }
    });
    return;
  }
  if (normalizedStatus !== "PROCESSING") {
    return;
  }
  stageOrder.forEach((key) => {
    if (!hasOwn(disclosureState.stageManual, key)) {
      disclosureState.stages[key] = key === stageKey;
    }
  });
}

function showFinalStage() {
  stageOrder.forEach((key) => {
    if (!hasOwn(disclosureState.stageManual, key)) {
      disclosureState.stages[key] = key === "results";
    }
  });
}

function createWorkflowState() {
  return {
    query: {
      number: "01",
      title: "Search Intent & Query",
      status: "WAITING",
      description: "LLM will translate the research question into a source-specific search query.",
      intent: "",
      searchPlan: null,
      source: "",
      query: "",
      bodyOverride: "",
    },
    search: {
      number: "02",
      title: "Search Iteration",
      status: "WAITING",
      description: "The selected database will be queried and adjusted by result counts.",
      history: [],
      finalQuery: "",
      preview: [],
      totalRecords: 0,
      auditData: null,
      queryPortfolio: [],
      bodyOverride: "",
    },
    ranking: {
      number: "03",
      title: "Candidate Retrieval & Ranking",
      status: "WAITING",
      description: "Returned records will be ranked with available metadata and abstracts when present.",
      candidateCount: 0,
      rankedCount: 0,
      totalRecords: 0,
      topScore: 0,
      rankingSteps: [],
      auditData: null,
      bodyOverride: "",
    },
    results: {
      number: "04",
      title: "Literature Results",
      status: "WAITING",
      description: "Final ranked papers will appear here.",
      totalRecords: 0,
      outputCount: 0,
      highScoreCount: 0,
      topScore: 0,
      candidatePool: 0,
      citationAdds: 0,
      bodyOverride: "",
    },
  };
}

function compactText(value, limit = 150) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function intentSummary(item) {
  if (item.searchPlan && item.searchPlan.intent) {
    return String(item.searchPlan.intent);
  }
  const raw = String(item.intent || "").trim();
  const match = raw.match(/^intent:\s*(.+)$/im);
  return match ? match[1].trim() : (raw.split(/\r?\n/).find(Boolean) || "");
}

function mainHistoryRows(history) {
  return (Array.isArray(history) ? history : []).filter((row) => String(row.action || "") !== "portfolio");
}

function finalHistoryRow(history) {
  const rows = mainHistoryRows(history);
  return rows.length ? rows[rows.length - 1] : null;
}

function iterationCount(history) {
  return mainHistoryRows(history).reduce((maximum, row) => Math.max(maximum, Number(row.iteration || 0)), 0);
}

function rankingStepById(item, ids) {
  const candidates = new Set(Array.isArray(ids) ? ids : [ids]);
  return [...(item.rankingSteps || [])].reverse().find((step) => candidates.has(String(step.id || ""))) || null;
}

function activeRankingStep(item) {
  return [...(item.rankingSteps || [])].reverse().find((step) => String(step.status || "").toLowerCase() === "processing") || null;
}

function rankingLedgerSummary(item) {
  const state = (item.auditData && item.auditData.search_state) || {};
  const queue = state.candidate_queue || {};
  const ledgerSummary = queue.ledger_summary || {};
  return ledgerSummary.lifecycle_candidate_counts || {};
}

function stageSummary(key, item) {
  if (item.bodyOverride && item.status === "ERROR") {
    return item.description;
  }
  if (key === "query") {
    const intent = intentSummary(item);
    if (item.query) {
      const source = compactSourceLabels[item.source] || item.source || getValue("dataSource");
      return `${source} · ${compactText(item.query)}`;
    }
    return intent || item.description;
  }
  if (key === "search") {
    const rounds = iterationCount(item.history);
    const finalRow = finalHistoryRow(item.history);
    if (item.totalRecords || rounds || finalRow) {
      const action = finalRow ? translatedActionText(finalRow.action || "") : "";
      return localizedText(
        `${item.totalRecords || 0} hits · ${rounds} iteration${rounds === 1 ? "" : "s"}${action ? ` · ${action}` : ""}`,
        `${item.totalRecords || 0} 条命中 · ${rounds} 轮${action ? ` · ${action}` : ""}`,
      );
    }
    return item.description;
  }
  if (key === "ranking") {
    const active = activeRankingStep(item);
    if (active) {
      const progress = Number(active.total || 0) > 0 ? ` ${Number(active.current || 0)}/${Number(active.total || 0)}` : "";
      return `${translatedRuntimeText(active.title || active.id || "Ranking step")}${progress}`;
    }
    const lifecycle = rankingLedgerSummary(item);
    const selected = Number(lifecycle.selected_for_llm || 0) || Number((rankingStepById(item, ["llm_reranking", "llm_ranking", "result_ranking"]) || {}).candidate_count || 0);
    if (item.candidateCount || selected || item.rankedCount) {
      return localizedText(
        `${item.candidateCount || 0} candidates · ${selected} sent to LLM · ${item.rankedCount || 0} output`,
        `${item.candidateCount || 0} 个候选 · ${selected} 个送入 LLM · ${item.rankedCount || 0} 个输出`,
      );
    }
    return item.description;
  }
  if (key === "results" && ["READY", "EMPTY"].includes(item.status)) {
    return localizedText(
      `${item.outputCount || 0} ranked papers · ${item.highScoreCount || 0} scored 5 or higher`,
      `${item.outputCount || 0} 篇排序文献 · ${item.highScoreCount || 0} 篇达到 5 分`,
    );
  }
  return item.description;
}

function renderStageBody(key, item) {
  if (item.bodyOverride) {
    return item.bodyOverride;
  }
  if (key === "query") {
    return renderQueryStage(item);
  }
  if (key === "search") {
    return renderSearchStage(item);
  }
  if (key === "ranking") {
    return renderRankingStage(item);
  }
  return renderResultsStage(item);
}

function workflowCard(key, item, extraClass = "") {
  const expanded = Boolean(disclosureState.stages[key]);
  const statusClass = item.status.toLowerCase().replaceAll(" ", "-");
  const actionLabel = expanded ? "Hide stage details" : "View stage details";
  return `
    <article id="workflow-card-${escapeHtml(key)}" class="workflow-card ${expanded ? "is-expanded" : "is-collapsed"} ${extraClass}" data-stage-card="${escapeHtml(key)}">
      <button class="workflow-card-toggle" type="button" data-stage-toggle="${escapeHtml(key)}" aria-expanded="${expanded ? "true" : "false"}" aria-controls="workflow-stage-${escapeHtml(key)}" aria-label="${escapeHtml(translatedText(actionLabel))}">
        <span class="card-title"><span>${escapeHtml(item.number)}</span><h3>${escapeHtml(translatedText(item.title))}</h3></span>
        <span class="card-status-group">
          <span class="status-badge ${escapeHtml(statusClass)}">${escapeHtml(translatedText(item.status))}</span>
          <span class="disclosure-chevron" aria-hidden="true"></span>
        </span>
      </button>
      <p class="card-description">${escapeHtml(stageSummary(key, item))}</p>
      <div id="workflow-stage-${escapeHtml(key)}" class="workflow-card-body" ${expanded ? "" : "hidden"}>
        ${renderStageBody(key, item)}
      </div>
    </article>
  `;
}

function renderWorkflow() {
  if (activeView === "results") {
    workflow.innerHTML = renderResultsView();
    applyLanguage(workflow);
    renderStepLabel();
    return;
  }
  if (activeView === "citations") {
    workflow.innerHTML = renderCitationView();
    applyLanguage(workflow);
    renderStepLabel();
    renderCitationGraph();
    return;
  }
  if (activeView === "history") {
    workflow.innerHTML = renderHistoryView();
    applyLanguage(workflow);
    setTranslatedText(stepLabel, "History");
    return;
  }

  workflow.innerHTML = stageOrder.map((key) => {
    const item = workflowState[key];
    const extra = item.status === "PROCESSING" ? "processing-card" : item.status === "ERROR" ? "error-card" : "";
    return workflowCard(key, item, extra);
  }).join("");

  applyLanguage(workflow);
  renderStepLabel();
}

function renderStepLabel() {
  const activeIndex = stageOrder.findIndex((key) => workflowState[key].status === "PROCESSING");
  if (activeIndex >= 0) {
    const key = stageOrder[activeIndex];
    const activeStep = key === "ranking" ? activeRankingStep(workflowState.ranking) : null;
    const detail = activeStep
      ? `${translatedRuntimeText(activeStep.title || activeStep.id || "Ranking step")}${Number(activeStep.total || 0) > 0 ? ` ${Number(activeStep.current || 0)}/${Number(activeStep.total || 0)}` : ""}`
      : translatedText(workflowState[key].title);
    stepLabel.textContent = `${activeIndex + 1}/4 · ${detail}`;
  } else if (workflowState.results.status === "READY" || workflowState.results.status === "EMPTY") {
    stepLabel.textContent = activeLanguage === "zh"
      ? `4/4 · ${workflowState.results.outputCount || 0} 条结果`
      : `4/4 · ${workflowState.results.outputCount || 0} results`;
  } else {
    stepLabel.textContent = "0/4";
  }
}

function switchView(view) {
  activeView = view;
  document.body.dataset.view = view;
  viewTabs.forEach((tab) => {
    const isActive = tab.dataset.view === view;
    tab.classList.toggle("active", isActive);
    tab.classList.toggle("muted", !isActive);
  });
  renderWorkflow();
  if (view === "history") {
    loadHistoryRuns();
  }
}

function emptyState(text) {
  return `<div class="empty-state">${escapeHtml(translatedRuntimeText(text))}</div>`;
}

function chipList(items) {
  return `<div class="chip-list">${items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
}

function renderDisclosureSection(key, title, body, { defaultExpanded = false, badge = "", className = "" } = {}) {
  const expanded = isSectionExpanded(key, defaultExpanded);
  const actionLabel = expanded ? "Hide details" : "View details";
  return `
    <section class="disclosure-section ${escapeHtml(className)} ${expanded ? "is-expanded" : "is-collapsed"}">
      <button class="disclosure-toggle" type="button" data-section-toggle="${escapeHtml(key)}" aria-expanded="${expanded ? "true" : "false"}" aria-controls="disclosure-${escapeHtml(key)}" aria-label="${escapeHtml(translatedText(actionLabel))}">
        <span>${escapeHtml(translatedText(title))}</span>
        <span class="disclosure-toggle-meta">
          ${badge ? `<span class="disclosure-badge">${escapeHtml(badge)}</span>` : ""}
          <span class="disclosure-chevron" aria-hidden="true"></span>
        </span>
      </button>
      <div id="disclosure-${escapeHtml(key)}" class="disclosure-body" ${expanded ? "" : "hidden"}>${body}</div>
    </section>
  `;
}

function renderPlanValues(label, values) {
  const normalized = Array.isArray(values) ? values.filter(Boolean) : [];
  if (!normalized.length) {
    return "";
  }
  return `
    <div class="intent-detail-group">
      <strong>${escapeHtml(translatedText(label))}</strong>
      ${chipList(normalized)}
    </div>
  `;
}

function renderQueryViews(views) {
  if (!Array.isArray(views) || !views.length) {
    return "";
  }
  return `
    <div class="intent-detail-group">
      <strong>${escapeHtml(translatedText("Query views"))}</strong>
      <div class="query-view-list">
        ${views.map((view) => `
          <div class="query-view-row">
            <span>${escapeHtml(view.view_id || view.view_type || "query view")}</span>
            <small>${escapeHtml(view.view_type || "")}</small>
            ${view.purpose ? `<p>${escapeHtml(view.purpose)}</p>` : ""}
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderQueryStage(item) {
  if (!item.intent && !item.searchPlan && !item.query) {
    return item.status === "PROCESSING"
      ? emptyState("Calling the LLM to generate a source-specific query.")
      : emptyState("No query generated yet.");
  }
  const plan = item.searchPlan && typeof item.searchPlan === "object" ? item.searchPlan : {};
  const summary = intentSummary(item);
  const intentBlock = summary ? `
    <div class="intent-audit">
      <span>${escapeHtml(translatedRuntimeText("Interpreted intent"))}</span>
      <p>${escapeHtml(summary)}</p>
    </div>
  ` : "";
  const concepts = renderPlanValues("Core concepts", plan.core_concepts);
  const detailBody = [
    plan.question_type ? `<div class="intent-detail-line"><strong>${escapeHtml(translatedText("Question type"))}</strong><span>${escapeHtml(plan.question_type)}</span></div>` : "",
    renderPlanValues("Likely synonyms", plan.likely_synonyms),
    renderPlanValues("Adjacent concepts", plan.adjacent_concepts),
    renderPlanValues("Boundaries", plan.boundaries),
    renderPlanValues("Ambiguities", plan.ambiguities),
    plan.adjustment_strategy ? `<div class="intent-detail-line"><strong>${escapeHtml(translatedText("Adjustment strategy"))}</strong><span>${escapeHtml(plan.adjustment_strategy)}</span></div>` : "",
    renderQueryViews(plan.query_views),
  ].filter(Boolean).join("");
  const rawIntentFallback = !item.searchPlan && item.intent
    ? `<pre class="intent-raw">${escapeHtml(item.intent)}</pre>`
    : "";
  const details = detailBody
    ? renderDisclosureSection("intent-analysis", "Full intent analysis", detailBody)
    : rawIntentFallback
      ? renderDisclosureSection("intent-analysis", "Full intent analysis", rawIntentFallback)
      : renderDisclosureSection("intent-analysis", "Full intent analysis", emptyState("No structured intent details available."));
  const source = sourceLabels[item.source] || item.source || getValue("dataSource");
  const queryBlock = item.query ? `
    <div class="final-query query-output">
      <span>${escapeHtml(translatedText("Current query"))}</span>
      <small>${escapeHtml(translatedText(source))}</small>
      <code>${escapeHtml(item.query)}</code>
    </div>
  ` : emptyState("Calling the LLM to generate a source-specific query.");
  return `${intentBlock}${concepts}${details}${queryBlock}`;
}

function metricRow(items) {
  return `<div class="metric-row metric-count-${Math.min(4, items.length)}">${items.map((item) => `
    <div>
      <strong>${escapeHtml(item.value)}</strong>
      <span>${escapeHtml(translatedText(item.label))}</span>
    </div>
  `).join("")}</div>`;
}

function renderRankingStepRow(step, index, { current = false } = {}) {
  const total = Number(step.total || 0);
  const completed = Number(step.current || 0);
  const status = String(step.status || "processing").toLowerCase();
  const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((completed / total) * 100))) : 0;
  const hasProgress = total > 0 && ["processing", "complete"].includes(status);
  const title = translatedRuntimeText(step.title || step.id || "Ranking step");
  const detail = translatedRuntimeText(step.detail || "");
  const metaParts = [
    total > 0 ? `${completed}/${total}` : "",
    step.concurrency ? localizedText(`concurrency ${step.concurrency}`, `并发 ${step.concurrency}`) : "",
    step.candidate_count ? localizedText(`${step.candidate_count} candidates`, `${step.candidate_count} 个候选`) : "",
  ].filter(Boolean);
  const key = `ranking-step-${String(step.id || index).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const expanded = isSectionExpanded(key, current || status === "error");
  return `
    <section class="ranking-step-row ${escapeHtml(status)} ${current ? "current" : ""} ${expanded ? "is-expanded" : "is-collapsed"}">
      <button class="ranking-step-toggle" type="button" data-section-toggle="${escapeHtml(key)}" aria-expanded="${expanded ? "true" : "false"}" aria-controls="disclosure-${escapeHtml(key)}">
        <span class="ranking-step-name">${escapeHtml(title)}</span>
        <span class="ranking-step-summary">
          ${metaParts.length ? `<small>${escapeHtml(metaParts.join(" · "))}</small>` : ""}
          <span class="action-pill ${escapeHtml(status)}">${escapeHtml(translatedStatusText(status))}</span>
          <span class="disclosure-chevron" aria-hidden="true"></span>
        </span>
      </button>
      <div id="disclosure-${escapeHtml(key)}" class="ranking-step-body" ${expanded ? "" : "hidden"}>
        ${detail ? `<p>${escapeHtml(detail)}</p>` : ""}
        ${hasProgress ? `<div class="progress-bar" aria-label="${escapeHtml(`${title} ${translatedRuntimeText("progress")}`)}"><span style="width: ${percent}%"></span></div>` : ""}
      </div>
    </section>
  `;
}

function renderRankingStage(item) {
  if (item.status === "WAITING" && (!item.rankingSteps || !item.rankingSteps.length)) {
    return emptyState("No ranking request has run.");
  }
  const lifecycle = rankingLedgerSummary(item);
  const fusedStep = rankingStepById(item, ["citation_refusion", "rrf_fusion", "multi_lane_retrieval"]);
  const llmStep = rankingStepById(item, ["llm_reranking", "llm_ranking", "result_ranking"]);
  const fusedCandidates = Number((fusedStep || {}).candidate_count || 0) || Number(item.candidateCount || 0);
  const selectedForLlm = Number(lifecycle.selected_for_llm || 0) || Number((llmStep || {}).candidate_count || 0);
  const metrics = metricRow([
    { value: item.totalRecords || 0, label: "SOURCE HITS" },
    { value: fusedCandidates, label: "FUSED CANDIDATES" },
    { value: selectedForLlm, label: "SELECTED FOR LLM" },
    { value: item.rankedCount || 0, label: "FINAL OUTPUT" },
  ]);
  if (!item.rankingSteps || item.rankingSteps.length === 0) {
    return `${metrics}${emptyState("Waiting for ranking progress.")}`;
  }
  const currentStep = activeRankingStep(item);
  const currentOperation = currentStep ? `
    <div class="current-operation">
      <span>${escapeHtml(translatedText("Current operation"))}</span>
      ${renderRankingStepRow(currentStep, item.rankingSteps.indexOf(currentStep), { current: true })}
    </div>
  ` : "";
  const rows = item.rankingSteps
    .filter((step) => step !== currentStep)
    .map((step, index) => renderRankingStepRow(step, index))
    .join("");
  const audit = item.auditData ? renderSearchLoopAudit(item.auditData, "ranking") : "";
  return `${metrics}${currentOperation}${rows ? `<div class="ranking-step-list">${rows}</div>` : ""}${audit}`;
}

function compactActionSummary(items, fallback = "none") {
  const actions = (items || [])
    .map((item) => item && (item.action || item.status || item.error_type))
    .filter(Boolean)
    .map((action) => translatedActionText(action));
  if (!actions.length) {
    return translatedRuntimeText(fallback);
  }
  return [...new Set(actions)].slice(0, 8).join(" · ");
}

function recoveryIssueCount(state) {
  const ignored = new Set(["", "none", "completed", "complete"]);
  return [
    ...(state.recovery_decisions || []),
    ...(state.ranking_recovery_decisions || []),
    ...(state.citation_recovery_decisions || []),
  ].filter((item) => !ignored.has(String(item && (item.action || item.status || item.error_type) || "").toLowerCase())).length;
}

function renderSearchLoopAudit(data, mode = "search") {
  const loop = data.search_loop || {};
  const state = data.search_state || {};
  const queue = state.candidate_queue || {};
  const queueKeys = Array.isArray(queue.keys) ? queue.keys : [];
  const ledger = queue.ledger && typeof queue.ledger === "object" ? queue.ledger : {};
  const ledgerSummary = queue.ledger_summary && typeof queue.ledger_summary === "object" ? queue.ledger_summary : {};
  const selectorCounts = ledgerSummary.selector_counts && typeof ledgerSummary.selector_counts === "object"
    ? ledgerSummary.selector_counts
    : {};
  const lifecycleCounts = ledgerSummary.lifecycle_candidate_counts && typeof ledgerSummary.lifecycle_candidate_counts === "object"
    ? ledgerSummary.lifecycle_candidate_counts
    : {};
  const rankingGateCounts = ledgerSummary.ranking_gate_counts && typeof ledgerSummary.ranking_gate_counts === "object"
    ? ledgerSummary.ranking_gate_counts
    : {};
  const ledgerTotal = Number(ledgerSummary.total_candidates ?? Object.keys(ledger).length) || queueKeys.length;
  const ledgerRetained = Number(ledgerSummary.serialized_candidates ?? Object.keys(ledger).length) || 0;
  const uncertainCandidates = Number(selectorCounts.uncertain || 0);
  const selectedForLlm = Number(lifecycleCounts.selected_for_llm || 0);
  const finalOutputCandidates = Number(lifecycleCounts.final_output || 0);
  const observations = Array.isArray(state.observations) ? state.observations : [];
  const decisions = Array.isArray(state.decisions) ? state.decisions : [];
  const originCounts = queue.origin_counts && typeof queue.origin_counts === "object" ? queue.origin_counts : {};
  const originSummary = Object.entries(originCounts)
    .map(([origin, count]) => `${translatedRuntimeText(origin)} ${count}`)
    .join(" · ");
  const recoveryRows = [
    ["Source recovery", compactActionSummary(state.recovery_decisions)],
    ["Ranking recovery", compactActionSummary(state.ranking_recovery_decisions)],
    ["Citation recovery", compactActionSummary(state.citation_recovery_decisions)],
  ];
  const metrics = mode === "ranking"
    ? metricRow([
      { value: ledgerTotal, label: "LEDGER CANDIDATES" },
      { value: selectedForLlm, label: "SELECTED FOR LLM" },
      { value: finalOutputCandidates, label: "FINAL OUTPUT" },
    ])
    : metricRow([
      { value: loop.backend_used || loop.backend_requested || "unknown", label: "LOOP BACKEND" },
      { value: observations.length, label: "OBSERVATIONS" },
      { value: decisions.length, label: "DECISIONS" },
    ]);
  const detailLines = mode === "ranking"
    ? recoveryRows.map(([label, value]) => `${translatedRuntimeText(label)}: ${value}`)
    : [
      `${translatedRuntimeText("Loop decisions")}: ${compactActionSummary(decisions)}`,
      `${translatedRuntimeText("Candidate queue")}: ${queueKeys.length}${originSummary ? ` (${originSummary})` : ""}`,
      `${translatedRuntimeText("Duplicate candidates")}: ${queue.duplicate_count || 0}`,
      `${translatedRuntimeText("Candidate ledger")}: ${ledgerTotal}`,
      `${translatedRuntimeText("Ledger details retained")}: ${ledgerRetained}`,
      `${translatedRuntimeText("Uncertain candidates")}: ${uncertainCandidates}`,
    ];
  if (mode === "ranking") {
    detailLines.push(
      `${translatedRuntimeText("Selected for LLM")}: ${selectedForLlm}`,
      `${translatedRuntimeText("Final output candidates")}: ${finalOutputCandidates}`,
      `${translatedRuntimeText("Truncated before LLM")}: ${Number(rankingGateCounts.truncated || lifecycleCounts.truncated_before_llm || 0)}`,
      `${translatedRuntimeText("Ledger details retained")}: ${ledgerRetained}/${ledgerTotal}`,
    );
  }
  const content = `
    <div class="query-rationale loop-audit">
      ${metrics}
      <p>${escapeHtml(detailLines.join(" | "))}</p>
    </div>
  `;
  const issueCount = recoveryIssueCount(state);
  const title = mode === "ranking" ? "Recovery and candidate audit" : "Technical audit";
  const badge = issueCount
    ? localizedText(`${issueCount} recovered issue${issueCount === 1 ? "" : "s"}`, `${issueCount} 个已恢复问题`)
    : "";
  return renderDisclosureSection(`${mode}-audit`, title, content, { badge, className: "audit-disclosure" });
}

function renderIterationRows(history, stageStatus) {
  const rows = mainHistoryRows(history);
  if (!rows.length) {
    return emptyState("Waiting for the first source response.");
  }
  const lastIndex = rows.length - 1;
  return `
    <div class="iteration-list">
      ${rows.map((row, index) => {
        const key = `iteration-${index}-${String(row.action || "step").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
        const normalizedStageStatus = String(stageStatus || "").toUpperCase();
        const action = String(row.action || "").toLowerCase();
        const isAccepted = action === "accept" || action === "accept_low" || action === "accept_high" || action === "accept_pool";
        const defaultExpanded = index === lastIndex && (normalizedStageStatus === "PROCESSING" || (normalizedStageStatus === "COMPLETE" && isAccepted));
        const expanded = isSectionExpanded(key, defaultExpanded);
        const totalLabel = row.total === null || row.total === undefined
          ? translatedRuntimeText("No count")
          : localizedText(`${row.total} records`, `${row.total} 条记录`);
        return `
          <section class="iteration-row ${expanded ? "is-expanded" : "is-collapsed"}">
            <button class="iteration-toggle" type="button" data-section-toggle="${escapeHtml(key)}" aria-expanded="${expanded ? "true" : "false"}" aria-controls="disclosure-${escapeHtml(key)}">
              <span class="iteration-meta">
                <strong>${activeLanguage === "zh" ? `第 ${escapeHtml(row.iteration)} 轮` : `Iteration ${escapeHtml(row.iteration)}`}</strong>
                <span class="action-pill ${escapeHtml(row.action)}">${escapeHtml(translatedActionText(row.action))}</span>
                <span>${escapeHtml(totalLabel)}</span>
              </span>
              <span class="disclosure-chevron" aria-hidden="true"></span>
            </button>
            <div id="disclosure-${escapeHtml(key)}" class="iteration-body" ${expanded ? "" : "hidden"}>
              <code>${escapeHtml(row.query)}</code>
              ${row.message ? `<p>${escapeHtml(translatedRuntimeText(row.message))}</p>` : ""}
              ${row.rationale ? `<div class="query-rationale"><span>${escapeHtml(translatedRuntimeText("Adjustment rationale"))}</span><p>${escapeHtml(row.rationale)}</p></div>` : ""}
              ${row.next_query ? `<div class="next-query"><span>${escapeHtml(translatedRuntimeText("Next query"))}</span><code>${escapeHtml(row.next_query)}</code></div>` : ""}
            </div>
          </section>
        `;
      }).join("")}
    </div>
  `;
}

function renderQueryPortfolio(history, executions = []) {
  const structuredRows = Array.isArray(executions) ? executions : [];
  const rows = structuredRows.length
    ? structuredRows
    : (Array.isArray(history) ? history : []).filter((row) => String(row.action || "") === "portfolio");
  if (!rows.length) {
    return "";
  }
  const body = `
    <div class="portfolio-list">
      ${rows.map((row) => `
        <div class="portfolio-row">
          <div class="iteration-meta">
            <strong>${escapeHtml(row.view_id || row.rationale || translatedText("Query portfolio"))}</strong>
            <span class="action-pill ${escapeHtml(row.status || row.action || "complete")}">${escapeHtml(translatedActionText(row.status || row.action || "complete"))}</span>
            ${row.hit_count === null || row.hit_count === undefined
              ? `<span>${row.total === null || row.total === undefined ? escapeHtml(translatedRuntimeText("No count")) : escapeHtml(localizedText(`${row.total} records`, `${row.total} 条记录`))}</span>`
              : `<span>${escapeHtml(localizedText(`${row.hit_count} returned`, `返回 ${row.hit_count} 条`))}</span>`}
            ${row.added_unique === null || row.added_unique === undefined ? "" : `<span>${escapeHtml(localizedText(`${row.added_unique} unique added`, `新增 ${row.added_unique} 个唯一候选`))}</span>`}
          </div>
          ${row.query ? `<code>${escapeHtml(row.query)}</code>` : ""}
          ${row.message ? `<p>${escapeHtml(translatedRuntimeText(row.message))}</p>` : ""}
        </div>
      `).join("")}
    </div>
  `;
  return renderDisclosureSection("query-portfolio", "Query portfolio", body);
}

function renderHistory(history, finalQuery, preview, stageStatus = "PROCESSING", queryPortfolio = []) {
  const rows = renderIterationRows(history, stageStatus);
  const portfolio = renderQueryPortfolio(history, queryPortfolio);

  const candidates = preview && preview.length
    ? renderDisclosureSection("candidate-preview", "Candidate preview", renderCandidatePreview(preview))
    : "";
  const queryBlock = finalQuery ? `
    <div class="final-query">
      <span>${escapeHtml(translatedText("Current query"))}</span>
      <code>${escapeHtml(finalQuery)}</code>
    </div>
  ` : "";

  return `${queryBlock}${rows}${portfolio}${candidates}`;
}

function renderSearchStage(item) {
  if (!item.history.length && !item.finalQuery) {
    return item.status === "PROCESSING"
      ? emptyState("Waiting for the first source response.")
      : emptyState("No source request has run.");
  }
  const rounds = iterationCount(item.history);
  const finalRow = finalHistoryRow(item.history);
  const metrics = metricRow([
    { value: rounds, label: "ITERATIONS" },
    { value: item.totalRecords || 0, label: "FINAL HITS" },
    { value: finalRow ? translatedActionText(finalRow.action || "") : "-", label: "FINAL ACTION" },
  ]);
  const history = renderHistory(item.history, item.finalQuery, item.preview, item.status, item.queryPortfolio);
  const audit = item.auditData ? renderSearchLoopAudit(item.auditData, "search") : "";
  return `${metrics}${history}${audit}`;
}

function renderResultsStage(item) {
  if (item.status === "WAITING") {
    return emptyState("Run a search to populate the result list.");
  }
  const metrics = metricRow([
    { value: item.outputCount || 0, label: "RANKED RECORDS" },
    { value: item.highScoreCount || 0, label: "SCORED >= 5" },
    { value: item.topScore || 0, label: "TOP SCORE" },
    { value: item.citationAdds || 0, label: "CITATION ADDS" },
  ]);
  return `
    ${metrics}
    <div class="result-jump-actions">
      <button class="primary-inline-button" type="button" data-switch-view="results">${escapeHtml(translatedText("Review Results"))}</button>
      <button class="secondary-button" type="button" data-switch-view="citations">${escapeHtml(translatedText("Open Citation Map"))}</button>
    </div>
  `;
}

function renderCandidatePreview(preview) {
  if (!preview || preview.length === 0) {
    return "";
  }
  return `
    <div class="candidate-preview">
      ${preview.map((paper) => `
        <div class="candidate-row">
          <strong>${escapeHtml(paper.title || "(no title)")}</strong>
          <small>${escapeHtml([paper.year, paper.source, paper.provider].filter(Boolean).join(" | "))}</small>
        </div>
      `).join("")}
    </div>
  `;
}

function renderPapers(papers) {
  const normalizedPapers = normalizePapers(papers);
  if (!normalizedPapers || normalizedPapers.length === 0) {
    return emptyState("No ranked papers returned.");
  }
  return `
    <div class="paper-list">
      ${normalizedPapers.map((paper) => {
        const authors = paper.authors && paper.authors.length ? paper.authors.slice(0, 6).join(", ") : translatedText("No author metadata");
        const meta = [
          paper.provider || "",
          paper.publish_year || "",
          paper.citations ? `${paper.citations} ${translatedText("citations")}` : "",
          paper.source || "",
          paper.document_types && paper.document_types.length ? paper.document_types.join("; ") : "",
        ].filter(Boolean).join(" | ");
        const link = paper.links && paper.links.record ? `<a href="${escapeHtml(paper.links.record)}" target="_blank" rel="noreferrer">${escapeHtml(translatedText("Open source record"))}</a>` : "";
        const pdfLink = paper.links && paper.links.pdf ? `<a href="${escapeHtml(paper.links.pdf)}" target="_blank" rel="noreferrer">${escapeHtml(translatedText("Open PDF"))}</a>` : "";
        return `
          <details class="paper-row" open>
            <summary>
              <span class="score">${escapeHtml(paper.score ?? 0)}/10</span>
              <span class="paper-title">${escapeHtml(paper.title || "(no title)")}</span>
            </summary>
            <div class="paper-body">
              <p>${escapeHtml(authors)}</p>
              <p>${escapeHtml(meta)}</p>
              ${paper.keywords ? `<p><strong>${escapeHtml(translatedText("Keywords:"))}</strong> ${escapeHtml(paper.keywords)}</p>` : ""}
              ${paper.doi ? `<p><strong>DOI:</strong> ${escapeHtml(paper.doi)}</p>` : ""}
              ${paper.citations ? `<p><strong>${escapeHtml(translatedText("Citations:"))}</strong> ${escapeHtml(paper.citations)}</p>` : ""}
              ${paper.abstract ? `<p><strong>${escapeHtml(translatedText("Abstract:"))}</strong> ${escapeHtml(paper.abstract.slice(0, 900))}${paper.abstract.length > 900 ? "..." : ""}</p>` : ""}
              ${paper.reasoning ? `<p><strong>${escapeHtml(translatedText("Reasoning:"))}</strong> ${escapeHtml(paper.reasoning)}</p>` : ""}
              <div class="paper-links">${link} ${pdfLink}</div>
            </div>
          </details>
        `;
      }).join("")}
    </div>
  `;
}

function renderResultsView() {
  const allPapers = latestResult && latestResult.ranked ? latestResult.ranked : [];
  if (!latestResult) {
    return `
      <section class="workspace-view">
        <div class="workspace-header">
          <div>
            <div class="section-kicker">Results</div>
            <h2>${escapeHtml(translatedText("Ranked literature"))}</h2>
          </div>
        </div>
        ${emptyState("Run a search before reviewing results.")}
      </section>
    `;
  }

  const filtered = getFilteredPapers();
  const selectedCount = selectedPapers().length;
  return `
    <section class="workspace-view results-view">
      <div class="workspace-header">
        <div>
          <div class="section-kicker">Results</div>
          <h2>${escapeHtml(translatedText("Ranked literature"))}</h2>
        </div>
        <div class="view-actions">
          <span>${escapeHtml(filtered.length)} ${escapeHtml(translatedText("shown"))}</span>
          <span>${escapeHtml(selectedCount)} ${escapeHtml(translatedText("selected"))}</span>
        </div>
      </div>
      <div class="results-toolbar">
        <input id="resultSearch" type="search" value="${escapeHtml(resultFilters.query)}" placeholder="${escapeHtml(translatedText("Search title, author, abstract, DOI"))}">
        <select id="resultMinScore">
          <option value="all"${resultFilters.minScore === "all" ? " selected" : ""}>${escapeHtml(translatedText("All scores"))}</option>
          <option value="7"${resultFilters.minScore === "7" ? " selected" : ""}>${escapeHtml(translatedText("Score >= 7"))}</option>
          <option value="8"${resultFilters.minScore === "8" ? " selected" : ""}>${escapeHtml(translatedText("Score >= 8"))}</option>
          <option value="9"${resultFilters.minScore === "9" ? " selected" : ""}>${escapeHtml(translatedText("Score >= 9"))}</option>
        </select>
        <select id="resultAvailability">
          <option value="all"${resultFilters.availability === "all" ? " selected" : ""}>${escapeHtml(translatedText("All metadata"))}</option>
          <option value="abstract"${resultFilters.availability === "abstract" ? " selected" : ""}>${escapeHtml(translatedText("Has abstract"))}</option>
          <option value="doi"${resultFilters.availability === "doi" ? " selected" : ""}>${escapeHtml(translatedText("Has DOI"))}</option>
          <option value="pdf"${resultFilters.availability === "pdf" ? " selected" : ""}>${escapeHtml(translatedText("Has PDF"))}</option>
        </select>
        <select id="resultSort">
          <option value="rank"${resultFilters.sort === "rank" ? " selected" : ""}>${escapeHtml(translatedText("Sort by rank"))}</option>
          <option value="score"${resultFilters.sort === "score" ? " selected" : ""}>${escapeHtml(translatedText("Sort by score"))}</option>
          <option value="citations"${resultFilters.sort === "citations" ? " selected" : ""}>${escapeHtml(translatedText("Sort by citations"))}</option>
          <option value="year"${resultFilters.sort === "year" ? " selected" : ""}>${escapeHtml(translatedText("Sort by year"))}</option>
        </select>
        <button class="secondary-button" type="button" data-action="select-all-results">${escapeHtml(translatedText("Select all shown"))}</button>
        <button class="secondary-button" type="button" data-action="clear-result-selection">${escapeHtml(translatedText("Clear"))}</button>
        <button id="exportCsvButton" class="result-export-button" type="button" data-action="export-results-csv"${getExportPapers().length ? "" : " disabled"}>${escapeHtml(translatedText("Export Results CSV"))}</button>
      </div>
      ${filtered.length ? renderResultRows(filtered) : emptyState("No papers match the current filters.")}
    </section>
  `;
}

function renderResultRows(papers) {
  return `
    <div class="review-list">
      ${papers.map((paper) => {
        const id = paperId(paper);
        const checked = selectedPaperIds.has(id) ? " checked" : "";
        const authors = paper.authors && paper.authors.length ? paper.authors.slice(0, 8).join(", ") : translatedText("No author metadata");
        const meta = [
          `${translatedText("Rank")} ${paper.rank || ""}`,
          paper.score !== undefined ? `${paper.score}/10` : "",
          paper.publish_year || "",
          paper.citations ? `${paper.citations} ${translatedText("citations")}` : "",
          paper.source || "",
        ].filter(Boolean).join(" | ");
        const record = paper.links && paper.links.record ? `<a href="${escapeHtml(paper.links.record)}" target="_blank" rel="noreferrer">${escapeHtml(translatedText("Record"))}</a>` : "";
        const pdf = paper.links && paper.links.pdf ? `<a href="${escapeHtml(paper.links.pdf)}" target="_blank" rel="noreferrer">PDF</a>` : "";
        return `
          <details class="review-row" open>
            <summary>
              <input class="paper-select" type="checkbox" value="${escapeHtml(id)}"${checked} aria-label="${escapeHtml(translatedText("Select paper"))}">
              <span class="score">${escapeHtml(paper.score ?? 0)}/10</span>
              <span class="paper-title">${escapeHtml(paper.title || "(no title)")}</span>
            </summary>
            <div class="paper-body">
              <p>${escapeHtml(authors)}</p>
              <p>${escapeHtml(meta)}</p>
              ${paper.doi ? `<p><strong>DOI:</strong> ${escapeHtml(paper.doi)}</p>` : ""}
              ${paper.keywords ? `<p><strong>${escapeHtml(translatedText("Keywords:"))}</strong> ${escapeHtml(paper.keywords)}</p>` : ""}
              ${paper.abstract ? `<p><strong>${escapeHtml(translatedText("Abstract:"))}</strong> ${escapeHtml(paper.abstract.slice(0, 1400))}${paper.abstract.length > 1400 ? "..." : ""}</p>` : ""}
              ${paper.reasoning ? `<p><strong>${escapeHtml(translatedText("Reasoning:"))}</strong> ${escapeHtml(paper.reasoning)}</p>` : ""}
              <div class="paper-links">${record} ${pdf}</div>
            </div>
          </details>
        `;
      }).join("")}
    </div>
  `;
}

function shortText(value, maxChars = 120) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, maxChars - 3).trim()}...`;
}

function resultFromHistoryRun(run) {
  if (!run) {
    return null;
  }
  return {
    run_id: run.id,
    question: run.question || "",
    source: run.source || "",
    final_query: run.final_query || "",
    db: run.db || "",
    field: run.field || "",
    total: run.total || 0,
    iterations: run.iterations || 0,
    history: run.history || [],
    citation_map: run.citation_map || {},
    ranked: run.ranked || [],
  };
}

function renderHistoryView() {
  const statusText = historyStatus.enabled ? `Local SQLite: ${historyStatus.path || "default path"}` : "Local history is disabled";
  const selectedId = historyDetail && historyDetail.id ? historyDetail.id : "";
  const listBody = historyLoading ? emptyState("Loading saved runs.") : historyError ? `<div class="error-box">${escapeHtml(historyError)}</div>` : historyRuns.length ? `
    <div class="history-list">
      ${historyRuns.map((run) => {
        const active = run.id === selectedId ? " active" : "";
        const pieces = [
          run.status,
          run.source || "source pending",
          `${run.result_count || 0} papers`,
          run.checkpoint_stage ? `${translatedRuntimeText("Checkpoint")}: ${run.checkpoint_stage}` : "",
          run.created_at,
        ].filter(Boolean).join(" | ");
        return `
          <button class="history-run-button${active}" type="button" data-history-id="${escapeHtml(run.id)}">
            <strong>${escapeHtml(shortText(run.question || "(no question)", 96))}</strong>
            <span>${escapeHtml(pieces)}</span>
            ${run.final_query ? `<span>${escapeHtml(shortText(run.final_query, 110))}</span>` : ""}
          </button>
        `;
      }).join("")}
    </div>
  ` : emptyState("No saved search runs yet.");

  return `
    <section class="workspace-view history-view">
      <div class="workspace-header">
        <div>
          <div class="section-kicker">History</div>
          <h2>Local search records</h2>
        </div>
        <div class="view-actions">
          <span>${escapeHtml(statusText)}</span>
          <button class="secondary-button compact" type="button" data-history-action="refresh">Refresh</button>
        </div>
      </div>
      <div class="history-layout">
        <div>${listBody}</div>
        ${renderHistoryDetail()}
      </div>
    </section>
  `;
}

function renderHistoryDetail() {
  if (!historyDetail) {
    return `
      <div class="history-detail-panel">
        ${emptyState("Select a saved run to inspect query, events, and ranked papers.")}
      </div>
    `;
  }

  const run = historyDetail;
  const papers = run.ranked || [];
  const events = run.events || [];
  const meta = [
    run.status,
    run.source || "source pending",
    run.result_count !== undefined ? `${run.result_count} papers` : `${papers.length} papers`,
    run.iterations ? `${run.iterations} iteration(s)` : "",
    run.created_at,
  ].filter(Boolean);
  const eventRows = events.length ? `
    <div class="history-event-list">
      ${events.slice(-12).map((event) => `
        <div class="history-event-row">
          <span>${escapeHtml(String(event.created_at || "").slice(11, 19))}</span>
          <span>${escapeHtml(event.message || [event.type, event.stage, event.status].filter(Boolean).join(" "))}</span>
        </div>
      `).join("")}
    </div>
  ` : emptyState("No event log was saved for this run.");

  return `
    <div class="history-detail-panel">
      <div class="history-detail-head">
        <div class="section-kicker">${escapeHtml(run.id)}</div>
        <h3>${escapeHtml(run.question || "(no question)")}</h3>
        <div class="history-meta">${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
        <div class="result-jump-actions">
          <button class="primary-inline-button" type="button" data-history-action="open-results">Open Results</button>
          <button class="secondary-button" type="button" data-history-action="open-citations">Open Citation Map</button>
          ${run.resumable ? `<button class="secondary-button" type="button" data-history-action="resume">${escapeHtml(translatedRuntimeText("Resume from checkpoint"))}</button>` : ""}
          <button class="secondary-button" type="button" data-history-action="delete" data-history-id="${escapeHtml(run.id)}">Delete</button>
        </div>
      </div>
      ${run.final_query ? `
        <div class="history-query">
          <span>Final query</span>
          <code>${escapeHtml(run.final_query)}</code>
        </div>
      ` : ""}
      ${run.error_message ? `<div class="error-box">${escapeHtml(run.error_message)}</div>` : ""}
      ${papers.length ? renderPapers(papers.slice(0, 8)) : emptyState("This run did not save ranked papers.")}
      <div class="history-query">
        <span>Recent log events</span>
        ${eventRows}
      </div>
    </div>
  `;
}

async function loadHistoryRuns() {
  historyLoading = true;
  historyError = "";
  renderWorkflow();
  try {
    const response = await fetch("/api/history?limit=80");
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseErrorMessage(data, response.status));
    }
    historyStatus = { enabled: data.enabled, path: data.path };
    historyRuns = data.history || [];
    if (historyDetail && !historyRuns.some((run) => run.id === historyDetail.id)) {
      historyDetail = null;
    }
  } catch (error) {
    historyError = error.message;
  } finally {
    historyLoading = false;
    renderWorkflow();
  }
}

async function loadHistoryDetail(runIdValue) {
  historyError = "";
  try {
    const response = await fetch(`/api/history/${encodeURIComponent(runIdValue)}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseErrorMessage(data, response.status));
    }
    historyDetail = data;
  } catch (error) {
    historyError = error.message;
  }
  renderWorkflow();
}

function citationMap() {
  return latestResult && latestResult.citation_map ? latestResult.citation_map : null;
}

function citationRole(node) {
  const roles = node.roles || [];
  if (roles.includes("result")) return "result";
  if (roles.includes("seed")) return "seed";
  if (roles.includes("forward")) return "forward";
  if (roles.includes("backward")) return "backward";
  return "candidate";
}

function renderCitationView() {
  const map = citationMap();
  if (!latestResult) {
    return `
      <section class="workspace-view citation-view">
        <div class="workspace-header">
          <div>
            <div class="section-kicker">Citation Map</div>
            <h2>Citation expansion</h2>
          </div>
        </div>
        ${emptyState("Run an OpenAlex search with citation expansion enabled before exploring citations.")}
      </section>
    `;
  }
  if (!map || !map.enabled) {
    return `
      <section class="workspace-view citation-view">
        <div class="workspace-header">
          <div>
            <div class="section-kicker">Citation Map</div>
            <h2>Citation expansion</h2>
          </div>
        </div>
        ${emptyState("Citation expansion was disabled for this run.")}
      </section>
    `;
  }
  if (!map.supported) {
    return `
      <section class="workspace-view citation-view">
        <div class="workspace-header">
          <div>
            <div class="section-kicker">Citation Map</div>
            <h2>Citation expansion</h2>
          </div>
        </div>
        ${emptyState("Citation traversal is currently available for OpenAlex runs only.")}
      </section>
    `;
  }

  const nodes = map.nodes || [];
  const edges = map.edges || [];
  const seeds = nodes.filter((node) => (node.roles || []).includes("seed"));
  const promoted = nodes.filter((node) => (node.roles || []).includes("result") && !((node.roles || []).includes("seed")));
  const frontier = map.frontier && typeof map.frontier === "object" ? map.frontier : {};
  const frontierDirections = frontier.direction_stats && typeof frontier.direction_stats === "object" ? frontier.direction_stats : {};
  const backwardStats = frontierDirections.backward || {};
  const forwardStats = frontierDirections.forward || {};
  const frontierMetrics = frontier.planned_items ? `
    <div class="citation-summary-grid">
      ${metricRow([
        { value: `${frontier.processed_items || 0}/${frontier.planned_items || 0}`, label: "FRONTIER ITEMS" },
        { value: `${frontier.request_count || 0}/${frontier.request_budget || 0}`, label: "FRONTIER REQUESTS" },
        { value: backwardStats.added || 0, label: "BACKWARD ADDS" },
        { value: forwardStats.added || 0, label: "FORWARD ADDS" },
      ])}
      <div class="query-rationale loop-audit">
        <span>${escapeHtml(translatedRuntimeText("Citation frontier"))}</span>
        <p>${escapeHtml(`${translatedRuntimeText("Frontier stop reason")}: ${translatedActionText(frontier.stop_reason || "completed")}`)}</p>
      </div>
    </div>
  ` : "";
  return `
    <section class="workspace-view citation-view">
      <div class="workspace-header">
        <div>
          <div class="section-kicker">Citation Map</div>
          <h2>Citation expansion</h2>
        </div>
        <div class="view-actions">
          <span>${escapeHtml(nodes.length)} nodes</span>
          <span>${escapeHtml(edges.length)} edges</span>
        </div>
      </div>
      <div class="citation-summary-grid">
        ${metricRow([
          { value: map.initial_candidates || 0, label: "INITIAL CANDIDATES" },
          { value: map.seed_count || seeds.length || 0, label: "SEED PAPERS" },
          { value: map.added_candidates || 0, label: "ADDED CANDIDATES" },
          { value: promoted.length, label: "PROMOTED RESULTS" },
        ])}
      </div>
      ${frontierMetrics}
      <div class="citation-layout">
        <div class="citation-map-panel">
          <div class="citation-toolbar">
            <div class="citation-legend">
              <span><i class="legend-dot result"></i>Result</span>
              <span><i class="legend-dot seed"></i>Seed</span>
              <span><i class="legend-dot forward"></i>Forward citation</span>
              <span><i class="legend-dot backward"></i>Backward reference</span>
            </div>
            <div class="citation-controls">
              <button class="secondary-button compact" type="button" data-graph-action="zoom-out">-</button>
              <button class="secondary-button compact" type="button" data-graph-action="reset">Reset</button>
              <button class="secondary-button compact" type="button" data-graph-action="zoom-in">+</button>
              <select id="citationFocus">
                <option value="">All seeds</option>
                ${seeds.map((seed) => `<option value="${escapeHtml(seed.id)}">${escapeHtml((seed.title || seed.id).slice(0, 80))}</option>`).join("")}
              </select>
            </div>
          </div>
          <div id="citationGraph" class="citation-graph" aria-label="Citation network graph"></div>
        </div>
        <aside id="citationNodeDetail" class="citation-detail">
          ${renderCitationNodeDetail(nodes.find((node) => node.id === selectedCitationNodeId) || seeds[0] || nodes[0])}
        </aside>
      </div>
      <div class="seed-list">
        <h3>Seed papers</h3>
        ${seeds.length ? seeds.map((seed) => `
          <button type="button" class="seed-row" data-citation-node="${escapeHtml(seed.id)}">
            <strong>${escapeHtml(seed.title || seed.id)}</strong>
            <span>${escapeHtml([seed.year, seed.citations ? `${seed.citations} ${translatedText("citations")}` : "", seed.score ? `${seed.score}/10` : ""].filter(Boolean).join(" | "))}</span>
          </button>
        `).join("") : emptyState("No seed papers were recorded.")}
      </div>
    </section>
  `;
}

function renderCitationNodeDetail(node) {
  if (!node) {
    return emptyState("Select a node to inspect its metadata.");
  }
  const roles = (node.roles || []).join(", ");
  return `
    <div class="detail-kicker">${escapeHtml(roles || "node")}</div>
    <h3>${escapeHtml(node.title || node.id)}</h3>
    <p>${escapeHtml([node.year, node.source, node.citations ? `${node.citations} ${translatedText("citations")}` : ""].filter(Boolean).join(" | "))}</p>
    ${node.score !== undefined ? `<p><strong>Score:</strong> ${escapeHtml(node.score)}/10</p>` : ""}
    ${node.rank ? `<p><strong>Rank:</strong> ${escapeHtml(node.rank)}</p>` : ""}
    ${node.reasoning ? `<p><strong>${escapeHtml(translatedText("Reasoning:"))}</strong> ${escapeHtml(node.reasoning)}</p>` : ""}
    <div class="paper-links"><a href="${escapeHtml(node.id)}" target="_blank" rel="noreferrer">Open record</a></div>
  `;
}

function filteredCitationGraph() {
  const map = citationMap();
  const allNodes = map && map.nodes ? map.nodes : [];
  const allEdges = map && map.edges ? map.edges : [];
  const focus = document.getElementById("citationFocus") ? document.getElementById("citationFocus").value : "";
  if (!focus) {
    return { nodes: allNodes, edges: allEdges };
  }
  const keep = new Set([focus]);
  allEdges.forEach((edge) => {
    if (edge.seed === focus || edge.source === focus || edge.target === focus) {
      keep.add(edge.source);
      keep.add(edge.target);
    }
  });
  return {
    nodes: allNodes.filter((node) => keep.has(node.id)),
    edges: allEdges.filter((edge) => keep.has(edge.source) && keep.has(edge.target)),
  };
}

function renderCitationGraph() {
  const container = document.getElementById("citationGraph");
  if (!container) return;
  const { nodes, edges } = filteredCitationGraph();
  if (!nodes.length) {
    container.innerHTML = emptyState("No citation graph nodes are available for this run.");
    applyLanguage(container);
    return;
  }

  const width = Math.max(container.clientWidth || 760, 520);
  const height = Math.max(container.clientHeight || 460, 360);
  const nodeMap = new Map(nodes.map((node, i) => {
    const saved = citationGraphState.positions[node.id];
    return [node.id, {
      ...node,
      x: saved ? saved.x : width / 2 + Math.cos(i * 2.2) * width * 0.25,
      y: saved ? saved.y : height / 2 + Math.sin(i * 2.2) * height * 0.25,
      vx: 0,
      vy: 0,
    }];
  }));
  const graphEdges = edges.filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target));

  if (Object.keys(citationGraphState.positions).length === 0) {
    for (let tick = 0; tick < 90; tick += 1) {
      const values = [...nodeMap.values()];
      for (let i = 0; i < values.length; i += 1) {
        for (let j = i + 1; j < values.length; j += 1) {
          const a = values[i];
          const b = values[j];
          const dx = a.x - b.x || 0.01;
          const dy = a.y - b.y || 0.01;
          const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 16);
          const force = 720 / (distance * distance);
          a.vx += (dx / distance) * force;
          a.vy += (dy / distance) * force;
          b.vx -= (dx / distance) * force;
          b.vy -= (dy / distance) * force;
        }
      }
      graphEdges.forEach((edge) => {
        const a = nodeMap.get(edge.source);
        const b = nodeMap.get(edge.target);
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const desired = 150;
        const force = (distance - desired) * 0.012;
        a.vx += (dx / distance) * force;
        a.vy += (dy / distance) * force;
        b.vx -= (dx / distance) * force;
        b.vy -= (dy / distance) * force;
      });
      values.forEach((node) => {
        node.vx += (width / 2 - node.x) * 0.002;
        node.vy += (height / 2 - node.y) * 0.002;
        node.x = Math.min(width - 60, Math.max(60, node.x + node.vx));
        node.y = Math.min(height - 46, Math.max(46, node.y + node.vy));
        node.vx *= 0.82;
        node.vy *= 0.82;
      });
    }
  }

  nodeMap.forEach((node) => {
    node.radius = Math.min(18, 7 + Math.sqrt(Number(node.citations || 0)) / 12 + (node.score ? 2 : 0));
    citationGraphState.positions[node.id] = { x: node.x, y: node.y };
  });

  const svgEdges = graphEdges.map((edge) => {
    const a = nodeMap.get(edge.source);
    const b = nodeMap.get(edge.target);
    const points = citationEdgePoints(a, b, a.radius, b.radius);
    return `<line class="citation-edge" data-source="${escapeHtml(edge.source)}" data-target="${escapeHtml(edge.target)}" data-source-radius="${a.radius.toFixed(1)}" data-target-radius="${b.radius.toFixed(1)}" x1="${points.x1.toFixed(1)}" y1="${points.y1.toFixed(1)}" x2="${points.x2.toFixed(1)}" y2="${points.y2.toFixed(1)}"></line>`;
  }).join("");
  const svgNodes = [...nodeMap.values()].map((node) => {
    const role = citationRole(node);
    const radius = node.radius;
    const selected = node.id === selectedCitationNodeId ? " selected" : "";
    return `
      <g class="citation-node ${escapeHtml(role)}${selected}" data-citation-node="${escapeHtml(node.id)}" transform="translate(${node.x.toFixed(1)} ${node.y.toFixed(1)})">
        <circle class="citation-hit-target" r="${(radius + 8).toFixed(1)}"></circle>
        <circle class="citation-node-mark" r="${radius.toFixed(1)}"></circle>
        <text y="${(radius + 13).toFixed(1)}">${escapeHtml((node.title || node.id).slice(0, 28))}</text>
        <title>${escapeHtml(node.title || node.id)}</title>
      </g>
    `;
  }).join("");

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z"></path>
        </marker>
      </defs>
      <g id="citationGraphViewport" transform="translate(${citationGraphState.panX} ${citationGraphState.panY}) scale(${citationGraphState.scale})">
        <g>${svgEdges}</g>
        <g>${svgNodes}</g>
      </g>
    </svg>
  `;
  bindCitationGraphInteractions(container);
}

function clampGraphScale(value) {
  return Math.min(3.2, Math.max(0.45, value));
}

function applyCitationTransform() {
  const viewport = document.getElementById("citationGraphViewport");
  if (viewport) {
    viewport.setAttribute("transform", `translate(${citationGraphState.panX} ${citationGraphState.panY}) scale(${citationGraphState.scale})`);
  }
}

function citationEdgePoints(source, target, sourceRadius = 10, targetRadius = 10) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
  const ux = dx / distance;
  const uy = dy / distance;
  const sourceGap = Math.min(sourceRadius + 4, distance * 0.35);
  const targetGap = Math.min(targetRadius + 8, distance * 0.45);
  return {
    x1: source.x + ux * sourceGap,
    y1: source.y + uy * sourceGap,
    x2: target.x - ux * targetGap,
    y2: target.y - uy * targetGap,
  };
}

function updateCitationGraphDom() {
  const container = document.getElementById("citationGraph");
  if (!container) return;
  container.querySelectorAll(".citation-node").forEach((nodeEl) => {
    const id = nodeEl.dataset.citationNode;
    const pos = citationGraphState.positions[id];
    if (pos) {
      nodeEl.setAttribute("transform", `translate(${pos.x.toFixed(1)} ${pos.y.toFixed(1)})`);
    }
  });
  container.querySelectorAll(".citation-edge").forEach((edgeEl) => {
    const source = citationGraphState.positions[edgeEl.dataset.source];
    const target = citationGraphState.positions[edgeEl.dataset.target];
    if (source && target) {
      const points = citationEdgePoints(
        source,
        target,
        Number(edgeEl.dataset.sourceRadius || 10),
        Number(edgeEl.dataset.targetRadius || 10),
      );
      edgeEl.setAttribute("x1", points.x1.toFixed(1));
      edgeEl.setAttribute("y1", points.y1.toFixed(1));
      edgeEl.setAttribute("x2", points.x2.toFixed(1));
      edgeEl.setAttribute("y2", points.y2.toFixed(1));
    }
  });
}

function svgPoint(event, svg) {
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const transformed = point.matrixTransform(svg.getScreenCTM().inverse());
  return {
    x: (transformed.x - citationGraphState.panX) / citationGraphState.scale,
    y: (transformed.y - citationGraphState.panY) / citationGraphState.scale,
  };
}

function zoomCitationGraph(factor) {
  citationGraphState.scale = clampGraphScale(citationGraphState.scale * factor);
  applyCitationTransform();
}

function resetCitationGraphView() {
  citationGraphState.scale = 1;
  citationGraphState.panX = 0;
  citationGraphState.panY = 0;
  applyCitationTransform();
}

function bindCitationGraphInteractions(container) {
  const svg = container.querySelector("svg");
  if (!svg) return;

  container.onwheel = (event) => {
    event.preventDefault();
    zoomCitationGraph(event.deltaY < 0 ? 1.12 : 0.89);
  };

  svg.addEventListener("pointerdown", (event) => {
    const nodeEl = event.target.closest(".citation-node");
    if (nodeEl) {
      const id = nodeEl.dataset.citationNode;
      const pos = citationGraphState.positions[id] || { x: 0, y: 0 };
      const point = svgPoint(event, svg);
      citationGraphState.draggingNodeId = id;
      citationGraphState.dragOffsetX = point.x - pos.x;
      citationGraphState.dragOffsetY = point.y - pos.y;
      selectedCitationNodeId = id;
      const map = citationMap();
      const node = map && map.nodes ? map.nodes.find((item) => item.id === id) : null;
      const detail = document.getElementById("citationNodeDetail");
      if (detail) {
        detail.innerHTML = renderCitationNodeDetail(node);
      }
      svg.setPointerCapture(event.pointerId);
      event.preventDefault();
      return;
    }
    citationGraphState.panning = true;
    citationGraphState.lastX = event.clientX;
    citationGraphState.lastY = event.clientY;
    svg.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  svg.addEventListener("pointermove", (event) => {
    if (citationGraphState.draggingNodeId) {
      const point = svgPoint(event, svg);
      citationGraphState.positions[citationGraphState.draggingNodeId] = {
        x: point.x - citationGraphState.dragOffsetX,
        y: point.y - citationGraphState.dragOffsetY,
      };
      updateCitationGraphDom();
      return;
    }
    if (citationGraphState.panning) {
      citationGraphState.panX += event.clientX - citationGraphState.lastX;
      citationGraphState.panY += event.clientY - citationGraphState.lastY;
      citationGraphState.lastX = event.clientX;
      citationGraphState.lastY = event.clientY;
      applyCitationTransform();
    }
  });

  const endDrag = (event) => {
    citationGraphState.draggingNodeId = "";
    citationGraphState.panning = false;
    if (event && svg.hasPointerCapture(event.pointerId)) {
      svg.releasePointerCapture(event.pointerId);
    }
  };
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);
}

function applyStageEvent(event) {
  const stage = workflowState[event.stage];
  if (!stage) {
    return;
  }
  const data = event.data || {};
  const status = (event.status || "processing").toUpperCase();
  stage.status = status;
  syncStageDisclosure(event.stage, status);

  if (event.stage === "query") {
    stage.bodyOverride = "";
    if (data.intent) {
      stage.intent = data.intent;
    }
    if (data.source) {
      stage.source = data.source;
    }
    if (data.search_plan && typeof data.search_plan === "object") {
      stage.searchPlan = data.search_plan;
    }
    if (data.query) {
      stage.query = data.query;
    }
    if (status !== "PROCESSING" && !data.query && !stage.query) {
      stage.query = data.query || "No query returned";
    }
  }

  if (event.stage === "search") {
    stage.bodyOverride = "";
    if (Array.isArray(data.history)) {
      stage.history = data.history;
    }
    stage.finalQuery = data.final_query || data.query || stage.finalQuery || "";
    if (Array.isArray(data.preview)) {
      stage.preview = data.preview;
    }
    if (Array.isArray(data.query_portfolio)) {
      stage.queryPortfolio = data.query_portfolio;
    }
    if (data.total !== undefined && data.total !== null) {
      stage.totalRecords = Number(data.total || 0);
      stage.description = `Latest source response returned ${data.total} records.`;
    }
  }

  if (event.stage === "ranking") {
    stage.bodyOverride = "";
    stage.candidateCount = data.candidate_count ?? stage.candidateCount ?? 0;
    stage.rankedCount = data.ranked_count ?? stage.rankedCount ?? 0;
    stage.totalRecords = data.total ?? stage.totalRecords ?? 0;
    if (data.ranking_steps) {
      stage.rankingSteps = data.ranking_steps;
    }
  }

  if (event.stage === "results") {
    stage.bodyOverride = "";
    stage.totalRecords = Number(data.total || 0);
    stage.outputCount = Number(data.ranked_count || 0);
  }

  renderWorkflow();
}

function applyFinalResult(data) {
  latestResult = data;
  latestError = "";
  selectedPaperIds = new Set();
  selectedCitationNodeId = "";
  citationGraphState = createCitationGraphState();
  updateExportButtons();
  const hasResults = data.ranked && data.ranked.length > 0;
  workflowState.query.status = "COMPLETE";
  workflowState.query.intent = data.search_intent || workflowState.query.intent || "";
  workflowState.query.searchPlan = data.search_plan || workflowState.query.searchPlan || null;
  workflowState.query.source = data.source || data.db || "source";
  workflowState.query.query = data.final_query || "";

  workflowState.search.status = "COMPLETE";
  workflowState.search.history = data.history || [];
  workflowState.search.finalQuery = data.final_query || "";
  workflowState.search.preview = [];
  workflowState.search.queryPortfolio = data.query_portfolio || [];
  workflowState.search.totalRecords = Number(data.total || 0);
  workflowState.search.auditData = data;
  workflowState.search.description = `Accepted query returned ${data.total} total records.`;

  workflowState.ranking.status = "COMPLETE";
  workflowState.ranking.candidateCount = data.citation_map?.candidate_pool || data.ranked.length || 0;
  workflowState.ranking.rankedCount = data.ranked.length;
  workflowState.ranking.totalRecords = data.total;
  workflowState.ranking.topScore = hasResults ? Math.max(...data.ranked.map((p) => Number(p.score || 0))) : 0;
  workflowState.ranking.rankingSteps = data.ranking_steps || workflowState.ranking.rankingSteps || [];
  workflowState.ranking.auditData = data;

  workflowState.results.status = hasResults ? "READY" : "EMPTY";
  const citationMap = data.citation_map || {};
  workflowState.results.totalRecords = Number(data.total || 0);
  workflowState.results.outputCount = data.ranked ? data.ranked.length : 0;
  workflowState.results.highScoreCount = (data.ranked || []).filter((entry) => Number(entry.score || 0) >= 5).length;
  workflowState.results.topScore = workflowState.ranking.topScore;
  workflowState.results.candidatePool = citationMap.candidate_pool || workflowState.results.outputCount;
  workflowState.results.citationAdds = Number(citationMap.added_candidates || 0);
  showFinalStage();
  renderWorkflow();
}

function showClientError(message, fieldId) {
  workflowState = createWorkflowState();
  resetDisclosureState();
  workflowState.query.status = "ERROR";
  workflowState.query.title = "Input Required";
  workflowState.query.description = "Fill the required field and run the search again.";
  workflowState.query.bodyOverride = `<div class="error-box">${escapeHtml(message)}</div>`;
  disclosureState.stages.query = true;
  renderWorkflow();
  log(`Input required: ${message}`);
  if (fieldId) {
    const field = document.getElementById(fieldId);
    if (field) {
      field.classList.add("is-invalid");
      field.focus();
    }
  }
}

function showRunError(message) {
  latestError = message;
  updateExportButtons();
  setTranslatedText(stateLabel, "Error");
  workflowState.results.status = "ERROR";
  workflowState.results.title = "Search Failed";
  workflowState.results.description = "The local backend or upstream service returned an error.";
  workflowState.results.bodyOverride = `<div class="error-box">${escapeHtml(message)}</div>`;
  disclosureState.stages.results = true;
  setLogPanelExpanded(true, { error: true });
  renderWorkflow();
  log(`Error: ${message}`);
}

function hideConfigAlert() {
  if (configAlert) {
    configAlert.classList.add("is-hidden");
  }
}

function showConfigAlert(title, message, checks = []) {
  if (!configAlert || !configAlertTitle || !configAlertMessage || !configAlertList) {
    return;
  }
  setTranslatedText(configAlertTitle, title);
  setTranslatedText(configAlertMessage, message);
  configAlertList.textContent = "";
  const displayChecks = checks.length ? checks : [{ summary: message, actions: [] }];
  displayChecks.slice(0, 6).forEach((check) => {
    const item = document.createElement("li");
    const summary = document.createElement("strong");
    setTranslatedText(summary, check.summary || check.id || "Configuration check failed.");
    item.appendChild(summary);
    const actions = Array.isArray(check.actions) ? check.actions : [];
    actions.slice(0, 4).forEach((action) => {
      const actionNode = document.createElement("span");
      setTranslatedText(actionNode, action);
      item.appendChild(actionNode);
    });
    configAlertList.appendChild(item);
  });
  applyLanguage(configAlert);
  configAlert.classList.remove("is-hidden");
  setLogPanelExpanded(true, { error: true });
  if (configAlertCloseButton) {
    configAlertCloseButton.focus();
  }
}

function showRunStopped() {
  latestError = "Search stopped by user.";
  updateExportButtons();
  setTranslatedText(stateLabel, "Stopped");
  workflowState.results.status = "EMPTY";
  workflowState.results.title = "Search Stopped";
  workflowState.results.description = "The request was stopped before completion.";
  workflowState.results.bodyOverride = emptyState("No final result was produced for this run.");
  showFinalStage();
  renderWorkflow();
  log("Search stopped by user.");
}

function requestBackendCancel(runIdValue) {
  const id = String(runIdValue || "").trim();
  if (!id) {
    return;
  }
  fetch(`/api/search/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    keepalive: true,
  }).then((response) => {
    if (response.ok) {
      log(`Backend cancellation requested for ${id}.`);
    }
  }).catch(() => {
    // The client is stopping anyway; late cancellation failures should not
    // block the local UI from returning to an idle state.
  });
}

function validatePayload(payload) {
  const required = [
    ["question", "Research Question", "question"],
  ];
  for (const [key, label, fieldId] of required) {
    if (!String(payload[key] || "").trim()) {
      return { ok: false, message: `${label} is required.`, fieldId };
    }
  }
  if (payload.data_source === "wos" && !String(payload.wos_api_key || "").trim() && !environmentConfig.has_wos_api_key) {
    return { ok: false, message: "WoS API Key is required for WoS searches.", fieldId: "wosApiKey" };
  }
  if (payload.data_source === "googlescholar" && !String(payload.serper_api_key || "").trim() && !environmentConfig.has_serper_api_key) {
    return { ok: false, message: "Serper API Key is required for Google Scholar searches.", fieldId: "serperApiKey" };
  }
  if (payload.llm_provider !== "ollama" && !String(payload.llm_api_key || "").trim() && !envLlmKeyApplies(payload.llm_provider)) {
    return { ok: false, message: "LLM API Key is required for this provider.", fieldId: "llmApiKey" };
  }
  if (!String(payload.llm_api_type || "").trim()) {
    return { ok: false, message: "API Type is required.", fieldId: "llmApiType" };
  }
  if (!Number.isFinite(payload.target_min) || !Number.isFinite(payload.target_max)) {
    return { ok: false, message: "Min Results and Max Results must be numbers.", fieldId: "targetMin" };
  }
  if (payload.target_min > payload.target_max) {
    return { ok: false, message: "Min Results cannot exceed Max Results.", fieldId: "targetMin" };
  }
  return { ok: true };
}

function responseErrorMessage(data, status) {
  const detail = data && data.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join(" ");
  }
  if (detail && typeof detail === "object") {
    return detail.msg || JSON.stringify(detail);
  }
  return `HTTP ${status}`;
}

function buildPayload() {
  return {
    question: getValue("question"),
    data_source: getValue("dataSource"),
    search_budget: selectedSearchBudget(),
    wos_api_key: getValue("wosApiKey"),
    openalex_api_key: getValue("openAlexApiKey"),
    openalex_email: getValue("openAlexEmail"),
    crossref_email: getValue("crossrefEmail"),
    semantic_scholar_api_key: getValue("semanticScholarApiKey"),
    pubmed_api_key: getValue("pubmedApiKey"),
    pubmed_email: getValue("pubmedEmail"),
    pubmed_tool: getValue("pubmedTool") || "paperseek",
    serper_api_key: getValue("serperApiKey"),
    llm_api_key: getValue("llmApiKey"),
    llm_provider: getValue("llmProvider"),
    llm_api_type: getValue("llmApiType"),
    llm_model: getValue("llmModel"),
    llm_base_url: getValue("llmBaseUrl"),
    retrieval_embedding_provider: getValue("retrievalEmbeddingProvider") || "local",
    retrieval_embedding_model: getValue("retrievalEmbeddingModel"),
    retrieval_embedding_base_url: getValue("retrievalEmbeddingBaseUrl"),
    retrieval_embedding_api_key: getValue("retrievalEmbeddingApiKey"),
    retrieval_reranker_provider: getValue("retrievalRerankerProvider"),
    retrieval_reranker_model: getValue("retrievalRerankerModel"),
    retrieval_reranker_base_url: getValue("retrievalRerankerBaseUrl"),
    retrieval_reranker_api_key: getValue("retrievalRerankerApiKey"),
    wos_db: getValue("wosDb") || "WOS",
    search_field: getValue("searchField"),
    discipline_fields: selectedDisciplineFields(),
    client_timezone: clientTimeZone,
    client_utc_offset_minutes: clientUtcOffsetMinutes(),
    target_min: getNumber("targetMin"),
    target_max: getNumber("targetMax"),
    fetch_abstracts: document.getElementById("fetchAbstracts").checked,
    expand_citations: document.getElementById("expandCitations").checked,
    resume_run_id: pendingResumeRunId,
  };
}

async function checkConfiguration() {
  clearValidationState();
  hideConfigAlert();
  const payload = buildPayload();
  if (!String(payload.question || "").trim()) {
    payload.question = "machine learning";
  }
  log("Configuration check started.");
  checkConfigButton.disabled = true;
  try {
    const response = await fetch("/api/diagnostics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    log(`Backend POST /api/diagnostics -> HTTP ${response.status} ${response.ok ? "OK" : "ERROR"}.`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseErrorMessage(data, response.status));
    }
    log(`Doctor status: ${String(data.status || "unknown").toUpperCase()}.`);
    (data.checks || []).forEach((check) => {
      const label = String(check.status || "info").toUpperCase();
      log(`[${label}] ${check.summary || check.id || "diagnostic check"}`);
      (check.actions || []).forEach((action) => log(`  - ${action}`));
    });
    if (String(data.status || "").toLowerCase() === "fail") {
      const failedChecks = (data.checks || []).filter((check) => String(check.status || "").toLowerCase() === "fail");
      showConfigAlert(
        "Configuration failed",
        "Fix the items below before running a search.",
        failedChecks,
      );
    }
  } catch (error) {
    log(`Configuration check error: ${error.message}`);
    showConfigAlert(
      "Configuration check failed",
      "PaperSeek could not complete the configuration check.",
      [{ summary: error.message, actions: ["Review the required model and source settings, then run Check Config again."] }],
    );
  } finally {
    checkConfigButton.disabled = false;
  }
}

function updateSourceFields() {
  const source = dataSourceSelect.value;
  document.querySelectorAll(".source-field").forEach((node) => node.classList.add("is-hidden"));
  document.querySelectorAll(`.source-${source}`).forEach((node) => node.classList.remove("is-hidden"));
  updateSourceSummary();
}

async function readNdjsonStream(response, signal, searchToken) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    if ((signal && signal.aborted) || searchToken !== activeSearchToken) {
      break;
    }
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    if ((signal && signal.aborted) || searchToken !== activeSearchToken) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if ((signal && signal.aborted) || searchToken !== activeSearchToken) {
        break;
      }
      if (!line.trim()) {
        continue;
      }
      handleStreamEvent(JSON.parse(line));
    }
  }
  if (buffer.trim() && !(signal && signal.aborted) && searchToken === activeSearchToken) {
    handleStreamEvent(JSON.parse(buffer));
  }
}

function handleStreamEvent(event) {
  if (event.type === "log") {
    log(event.message || "");
  } else if (event.type === "heartbeat") {
    const now = Date.now();
    if (!latestStreamHeartbeatLogAt || now - latestStreamHeartbeatLogAt >= 30000) {
      latestStreamHeartbeatLogAt = now;
      log("Backend keepalive received; still waiting for upstream services.");
    }
  } else if (event.type === "run") {
    if (event.run_id) {
      activeBackendRunId = event.run_id;
      runId.textContent = event.run_id;
      log(`Local history run: ${event.run_id}.`);
    }
  } else if (event.type === "stage") {
    applyStageEvent(event);
  } else if (event.type === "result") {
    applyFinalResult(event.data);
  } else if (event.type === "cancelled") {
    showRunStopped();
  } else if (event.type === "error") {
    showRunError(event.message || "Unknown error");
  }
}

function applyProviderDefaults() {
  const defaults = providerDefaults[providerSelect.value] || providerDefaults.custom;
  apiTypeSelect.value = defaults.apiType;
  modelInput.value = defaults.model;
  baseUrlInput.value = defaults.baseUrl;
  updateCredentialPlaceholders();
}

providerSelect.addEventListener("change", applyProviderDefaults);

function applyRetrievalProviderDefaults(kind) {
  const isReranker = kind === "reranker";
  const select = isReranker ? retrievalRerankerProviderSelect : retrievalEmbeddingProviderSelect;
  const modelInputElement = isReranker ? retrievalRerankerModelInput : retrievalEmbeddingModelInput;
  const baseUrlInputElement = isReranker ? retrievalRerankerBaseUrlInput : retrievalEmbeddingBaseUrlInput;
  if (!select || !modelInputElement || !baseUrlInputElement) {
    return;
  }
  const defaults = retrievalProviderDefaults[select.value] || retrievalProviderDefaults.custom;
  modelInputElement.value = isReranker ? defaults.rerankerModel : defaults.embeddingModel;
  baseUrlInputElement.value = isReranker ? (defaults.rerankerBaseUrl || defaults.baseUrl) : (defaults.embeddingBaseUrl || defaults.baseUrl);
}

if (retrievalEmbeddingProviderSelect) {
  retrievalEmbeddingProviderSelect.addEventListener("change", () => applyRetrievalProviderDefaults("embedding"));
}
if (retrievalRerankerProviderSelect) {
  retrievalRerankerProviderSelect.addEventListener("change", () => applyRetrievalProviderDefaults("reranker"));
}

if (stopButton) {
  stopButton.addEventListener("click", () => {
    if (!activeSearchController) {
      return;
    }
    const controller = activeSearchController;
    setTranslatedText(stateLabel, "Stopping");
    log("Stop requested.");
    requestBackendCancel(activeBackendRunId);
    activeSearchToken += 1;
    activeSearchController = null;
    stopButton.disabled = true;
    controller.abort();
    showRunStopped();
    setBusy(false);
    updateExportButtons();
  });
}

if (logToggle) {
  logToggle.addEventListener("click", () => {
    logHasError = false;
    setLogPanelExpanded(!logPanelExpanded);
  });
}

if (configAlertCloseButton) {
  configAlertCloseButton.addEventListener("click", hideConfigAlert);
}

if (configAlertAdvancedButton) {
  configAlertAdvancedButton.addEventListener("click", () => {
    if (advancedSettings) {
      advancedSettings.open = true;
    }
    hideConfigAlert();
  });
}

if (configAlert) {
  configAlert.addEventListener("click", (event) => {
    if (event.target === configAlert) {
      hideConfigAlert();
    }
  });
}

viewTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view || "search"));
});

workflow.addEventListener("click", (event) => {
  const stageToggle = event.target.closest("[data-stage-toggle]");
  if (stageToggle) {
    const key = stageToggle.dataset.stageToggle;
    if (stageOrder.includes(key)) {
      disclosureState.stages[key] = !Boolean(disclosureState.stages[key]);
      disclosureState.stageManual[key] = true;
      renderWorkflow();
    }
    return;
  }

  const sectionToggle = event.target.closest("[data-section-toggle]");
  if (sectionToggle) {
    const key = sectionToggle.dataset.sectionToggle;
    const expanded = sectionToggle.getAttribute("aria-expanded") === "true";
    disclosureState.sections[key] = !expanded;
    renderWorkflow();
    return;
  }

  const switchTarget = event.target.closest("[data-switch-view]");
  if (switchTarget) {
    switchView(switchTarget.dataset.switchView);
    return;
  }

  const historyRun = event.target.closest("[data-history-id]");
  if (historyRun && historyRun.classList.contains("history-run-button")) {
    loadHistoryDetail(historyRun.dataset.historyId);
    return;
  }

  const historyAction = event.target.closest("[data-history-action]");
  if (historyAction) {
    const action = historyAction.dataset.historyAction;
    if (action === "refresh") {
      loadHistoryRuns();
    } else if (action === "open-results" || action === "open-citations") {
      const restored = resultFromHistoryRun(historyDetail);
      if (restored) {
        latestResult = restored;
        selectedPaperIds = new Set();
        selectedCitationNodeId = "";
        citationGraphState = createCitationGraphState();
        updateExportButtons();
        switchView(action === "open-results" ? "results" : "citations");
      }
    } else if (action === "resume" && historyDetail && historyDetail.resumable) {
      const questionInput = document.getElementById("question");
      if (questionInput) {
        questionInput.value = historyDetail.question || "";
      }
      if (historyDetail.source && [...dataSourceSelect.options].some((option) => option.value === historyDetail.source)) {
        dataSourceSelect.value = historyDetail.source;
        updateSourceFields();
        updateSourceFilterUi({ reset: true });
      }
      if (historyDetail.params && historyDetail.params.search_budget) {
        setSearchBudget(historyDetail.params.search_budget);
      }
      pendingResumeRunId = historyDetail.id;
      switchView("search");
      form.requestSubmit();
    } else if (action === "delete") {
      const targetId = historyAction.dataset.historyId || (historyDetail && historyDetail.id);
      if (targetId && window.confirm(`Delete local history run ${targetId}?`)) {
        fetch(`/api/history/${encodeURIComponent(targetId)}`, { method: "DELETE" })
          .then((response) => {
            if (!response.ok) {
              throw new Error(`HTTP ${response.status}`);
            }
            if (historyDetail && historyDetail.id === targetId) {
              historyDetail = null;
            }
            return loadHistoryRuns();
          })
          .catch((error) => {
            historyError = error.message;
            renderWorkflow();
          });
      }
    }
    return;
  }

  const graphAction = event.target.closest("[data-graph-action]");
  if (graphAction) {
    const action = graphAction.dataset.graphAction;
    if (action === "zoom-in") {
      zoomCitationGraph(1.18);
    } else if (action === "zoom-out") {
      zoomCitationGraph(0.85);
    } else {
      resetCitationGraphView();
    }
    return;
  }

  if (event.target.classList.contains("paper-select")) {
    event.stopPropagation();
    return;
  }

  const selectAll = event.target.closest("[data-action='select-all-results']");
  if (selectAll) {
    getFilteredPapers().forEach((paper) => selectedPaperIds.add(paperId(paper)));
    updateExportButtons();
    renderWorkflow();
    return;
  }

  const clearSelection = event.target.closest("[data-action='clear-result-selection']");
  if (clearSelection) {
    selectedPaperIds.clear();
    updateExportButtons();
    renderWorkflow();
    return;
  }

  const exportResults = event.target.closest("[data-action='export-results-csv']");
  if (exportResults) {
    exportResultsCsv();
    return;
  }

  const citationNode = event.target.closest("[data-citation-node]");
  if (citationNode) {
    selectedCitationNodeId = citationNode.dataset.citationNode;
    const detail = document.getElementById("citationNodeDetail");
    const map = citationMap();
    const node = map && map.nodes ? map.nodes.find((item) => item.id === selectedCitationNodeId) : null;
    if (detail) {
      detail.innerHTML = renderCitationNodeDetail(node);
      applyLanguage(detail);
    }
    renderCitationGraph();
  }
});

workflow.addEventListener("change", (event) => {
  if (event.target.classList.contains("paper-select")) {
    const id = event.target.value;
    if (event.target.checked) {
      selectedPaperIds.add(id);
    } else {
      selectedPaperIds.delete(id);
    }
    updateExportButtons();
    renderWorkflow();
    return;
  }

  if (event.target.id === "resultMinScore") {
    resultFilters.minScore = event.target.value;
    renderWorkflow();
  } else if (event.target.id === "resultAvailability") {
    resultFilters.availability = event.target.value;
    renderWorkflow();
  } else if (event.target.id === "resultSort") {
    resultFilters.sort = event.target.value;
    renderWorkflow();
  } else if (event.target.id === "citationFocus") {
    citationGraphState = createCitationGraphState();
    renderCitationGraph();
  }
  updateExportButtons();
});

workflow.addEventListener("input", (event) => {
  if (event.target.id === "resultSearch") {
    resultFilters.query = event.target.value;
    clearTimeout(resultSearchTimer);
    resultSearchTimer = setTimeout(() => {
      renderWorkflow();
      const input = document.getElementById("resultSearch");
      if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      updateExportButtons();
    }, 180);
  }
});

exportLogButton.addEventListener("click", () => {
  const filename = `${filenamePart(exportQuestionTheme())}-${dateStamp()}-system-log.txt`;
  downloadText(filename, currentLogText(), "text/plain;charset=utf-8");
});

checkConfigButton.addEventListener("click", checkConfiguration);

if (disciplineOptionsContainer) {
  disciplineOptionsContainer.addEventListener("change", updateDisciplineSummary);
}

if (clearDisciplinesButton) {
  clearDisciplinesButton.addEventListener("click", () => {
    setSelectedDisciplineFields([]);
  });
}

searchBudgetInputs.forEach((input) => {
  input.addEventListener("change", updateSearchBudgetHelp);
});

dataSourceSelect.addEventListener("change", () => {
  updateSourceFields();
  updateSourceFilterUi({ reset: true });
  workflowState = createWorkflowState();
  resetDisclosureState();
  renderWorkflow();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearValidationState();
  logOutput.textContent = "";
  resetLogPanel();
  const payload = buildPayload();
  latestPayload = null;
  latestResult = null;
  latestError = "";
  activeBackendRunId = "";
  selectedPaperIds = new Set();
  selectedCitationNodeId = "";
  citationGraphState = createCitationGraphState();
  resultFilters = { query: "", minScore: "all", availability: "all", sort: "rank" };
  updateExportButtons();
  const validation = validatePayload(payload);
  if (!validation.ok) {
    showClientError(validation.message, validation.fieldId);
    return;
  }
  latestPayload = payload;
  pendingResumeRunId = "";
  updateExportButtons();

  const id = `run_${Date.now().toString(36)}`;
  runId.textContent = id;
  workflowState = createWorkflowState();
  resetDisclosureState();
  workflowState.query.status = "PROCESSING";
  workflowState.query.bodyOverride = emptyState("Submitting request to local backend.");
  disclosureState.stages.query = true;
  renderWorkflow();
  setBusy(true);
  latestStreamHeartbeatLogAt = 0;
  const controller = new AbortController();
  activeSearchController = controller;
  const searchToken = ++activeSearchToken;
  log(`Run ${id} started.`);
  log(`Source: ${payload.data_source}; search budget: ${payload.search_budget}; provider: ${payload.llm_provider}; api type: ${payload.llm_api_type}; model: ${payload.llm_model || "provider default"}.`);
  log(`Initial query target: ${payload.target_min}-${payload.target_max}.`);

  try {
    const response = await fetch("/api/search/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    log(`Backend POST /api/search/stream -> HTTP ${response.status} ${response.ok ? "OK" : "ERROR"}.`);
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}));
      throw new Error(responseErrorMessage(data, response.status));
    }
    await readNdjsonStream(response, controller.signal, searchToken);
  } catch (error) {
    if (searchToken !== activeSearchToken) {
      // The user has already stopped this run; ignore late stream/abort errors.
    } else if (error.name === "AbortError") {
      showRunStopped();
    } else {
      showRunError(error.message);
    }
  } finally {
    if (activeSearchController === controller) {
      activeSearchController = null;
    }
    if (searchToken === activeSearchToken) {
      setBusy(false);
    }
    updateExportButtons();
  }
});

async function initializeApp() {
  initLanguageControls();
  updateSearchBudgetHelp();
  if (advancedSettings) {
    advancedSettings.open = false;
  }
  updateSourceFields();
  applyProviderDefaults();
  applyRetrievalProviderDefaults("embedding");
  applyRetrievalProviderDefaults("reranker");
  await loadDisciplineOptions();
  await loadServerDefaults();
  updateSourceSummary();
  updateExportButtons();
  document.body.dataset.view = activeView;
  renderLogPanelState();
  renderWorkflow();
  log("Ready. Keys and endpoint settings are held only in this browser session.");
  applyLanguage();
}

initializeApp();
