import { expect, test, type Page } from "@playwright/test";

const runId = "99999999-9999-4999-8999-999999999999";
const startedAt = "2026-08-12T08:00:00Z";

const run = {
  id: runId,
  question: "Release UX regression audit",
  source: "openalex",
  status: "completed",
  current_step: "workflow.completed",
  last_event_sequence: 8,
  result_count: 1,
  warnings: [],
  created_at: startedAt,
  updated_at: startedAt,
  started_at: startedAt,
  finished_at: startedAt,
};

const events = [
  [1, "query.started", "query.analyze", { target_min: 5 }],
  [2, "query.planned", "query.plan", { intent: "Map the evidence", question_type: "broad", current_query: "release audit", query_views: [{ view_id: "direct", purpose: "Direct evidence" }] }],
  [3, "query.progress", "query.iterate", { iteration: 1, decision: "accept", hit_count: 8, total: 12 }],
  [4, "retrieval.completed", "retrieve.fuse", { candidate_count: 12, total_candidates: 10, completed_lanes: 2, total_lanes: 2, fusion: "rrf" }],
  [5, "ranking.started", "rank.results", { candidate_count: 10, batch_count: 2, concurrency: 2 }],
  [6, "ranking.completed", "rank.results", { candidate_count: 10, scored_count: 10, warning_count: 0 }],
  [7, "enrichment.completed", "enrich.abstracts", { enriched_count: 7, total: 10, unavailable_count: 3 }],
  [8, "workflow.completed", "workflow.completed", { result_count: 1, warning_count: 0 }],
].map(([sequence, event_type, stage, payload]) => ({
  run_id: runId,
  sequence,
  event_type,
  stage,
  occurred_at: startedAt,
  schema_version: 1,
  payload,
}));

async function mockRun(page: Page): Promise<void> {
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: run }));
  await page.route(`**/api/v1/runs/${runId}/events**`, (route) => route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    body: events.map((event) => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`).join(""),
  }));
  await page.route(`**/api/v1/runs/${runId}/audit**`, (route) => route.fulfill({
    json: {
      query_portfolio: [{ view_id: "direct", purpose: "Direct evidence", status: "completed", hit_count: 8 }],
      loop_decisions: [{ iteration: 1, decision: "accept" }],
      candidate_queue: { pending: 0, completed: 10 },
      candidate_lifecycle: { loaded: 12, ranked: 10 },
      recovery: { resumed: false },
    },
  }));
}

test("provider failures have distinct bilingual recovery guidance in the run view", async ({ page }) => {
  const cases = [
    ["provider_quota_exhausted", "The model service has insufficient credits or allowance. Check its account or choose another service.", "模型服务余额或额度不足，请检查对应账户或切换服务。"],
    ["provider_rate_limited", "The model service is rate limiting requests. Wait and retry, or choose another service.", "模型服务请求过于频繁，请稍后重试或切换服务。"],
    ["provider_unavailable", "The model service is temporarily unavailable. Retry later or choose another service.", "模型服务暂时不可用，请稍后重试或切换服务。"],
    ["provider_connection_failed", "Could not reach the model service. Check the endpoint and connection, then retry.", "无法连接模型服务，请检查服务地址和网络后重试。"],
    ["provider_authentication_failed", "The model service rejected access. Check the key and permissions, or reconnect the provider.", "模型服务拒绝访问，请检查密钥和权限，或重新授权。"],
    ["provider_request_rejected", "The model service rejected the request. Check the model and API settings.", "模型服务拒绝了请求，请检查模型和 API 配置。"],
    ["provider_invalid_response", "The model service returned an unusable response. Retry or choose another model.", "模型服务返回了无效响应，请重试或选择其他模型。"],
    ["connection_not_active", "The provider connection is no longer available. Reconnect or choose another service.", "推理连接已不可用，请重新授权或切换服务。"],
  ];
  await mockRun(page);
  for (const [code, english, chinese] of cases) {
    await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: { ...run, status: "failed", error_code: code, result_count: 0 } }));
    await page.goto(`/runs/${runId}`);
    const primary = page.getByTestId("run-primary-summary");
    await expect(primary).toContainText(english);
    await expect(primary).not.toContainText(code);
    await page.getByRole("button", { name: "中文" }).click();
    await expect(primary).toContainText(chinese);
    await expect(primary).not.toContainText(english);
    await page.setViewportSize({ width: 320, height: 844 });
    expect(await primary.getByRole("alert").evaluate(element => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
    await page.getByRole("button", { name: "EN", exact: true }).click();
  }
});

test("Chinese search localizes capability and credential structure supplied by the API", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("paperseek.locale", "zh"));
  await page.route("**/api/v1/sources", (route) => route.fulfill({
    json: {
      sources: [{
        id: "openalex",
        label: "OpenAlex",
        default: true,
        status: "available",
        api_key: "optional",
        capabilities: {
          filter: { mode: "native", label: "Fields of study", options: [{ id: "27", label: "Medicine", domain: "Health Sciences" }] },
          citation_expansion: true,
        },
        credential: {
          requirement: "optional",
          input_label: "OpenAlex API Key",
          guidance_label: "Get an OpenAlex key",
          guidance_url: "https://example.com/openalex",
        },
      }],
    },
  }));

  await page.goto("/search");
  await expect(page.getByTestId("source-filter")).toContainText("研究领域");
  await page.getByTestId("field-selector-toggle").click();
  await expect(page.getByTestId("source-filter")).toContainText("医学");
  await expect(page.getByTestId("source-filter")).toContainText("健康科学");
  await expect(page.getByTestId("source-credential")).toContainText("OpenAlex API 密钥");
  await expect(page.getByTestId("source-credential-requirement")).toHaveText("可选");
  await expect(page.getByTestId("source-credential").getByRole("link")).toHaveText("获取 OpenAlex API 密钥");
  await expect(page.getByText("Fields of study", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Medicine", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Health Sciences", { exact: true })).toHaveCount(0);
  await expect(page.getByText("optional", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Get an OpenAlex key", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "EN" }).click();
  await expect(page.getByTestId("source-filter")).toContainText("Fields of study");
  await expect(page.getByTestId("source-filter")).toContainText("Medicine");
  await expect(page.getByTestId("source-filter")).toContainText("Health Sciences");
  await expect(page.getByTestId("source-credential")).toContainText("OpenAlex API key");
  await expect(page.getByTestId("source-credential-requirement")).toHaveText("Optional");
  await expect(page.getByTestId("source-credential").getByRole("link")).toHaveText("Get OpenAlex API key");
});

test("all four workspace destinations remain discoverable before a run exists", async ({ page }) => {
  await page.route("**/api/v1/sources", (route) => route.fulfill({ json: { sources: [] } }));
  await page.goto("/search");
  const navigation = page.getByRole("navigation", { name: "Workspace section" });
  await expect(navigation.getByRole("link", { name: "Search", exact: true })).toBeVisible();
  await expect(navigation.getByRole("link", { name: /Results/ })).toBeVisible();
  await expect(navigation.getByRole("link", { name: /Citation Map/ })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "History", exact: true })).toBeVisible();
  await expect(navigation.getByRole("link", { name: /Results/ })).toHaveAttribute("aria-disabled", "true");
  await expect(navigation.getByRole("link", { name: /Citation Map/ })).toHaveAttribute("aria-disabled", "true");
  await navigation.getByRole("link", { name: /Results/ }).click({ force: true });
  await expect(page).toHaveURL(/\/search$/);
});

test("mobile keeps all four disabled-aware destinations visible without overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/sources", (route) => route.fulfill({ json: { sources: [] } }));
  await page.goto("/search");

  const navigation = page.getByRole("navigation", { name: "Workspace section" });
  await expect(navigation.getByRole("link", { name: "Search", exact: true })).toBeVisible();
  await expect(navigation.getByRole("link", { name: /Results/ })).toBeVisible();
  await expect(navigation.getByRole("link", { name: /Citation Map/ })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "History", exact: true })).toBeVisible();
  await expect(navigation.getByRole("link", { name: /Results/ })).toHaveAttribute("title", "Run a search or choose a history item first.");
  await navigation.getByRole("link", { name: /Citation Map/ }).click({ force: true });
  await expect(page).toHaveURL(/\/search$/);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("workflow primary stages and normal progress use structured facts while machine audit remains folded", async ({ page }) => {
  await mockRun(page);
  await page.goto(`/runs/${runId}`);

  await page.getByTestId("stage-query-toggle").click();
  await expect(page.getByTestId("stage-query").locator("pre")).toHaveCount(0);
  await expect(page.getByTestId("stage-query-audit")).not.toContainText("question_type");
  await page.getByTestId("stage-search-toggle").click();
  await expect(page.getByTestId("stage-search").locator("pre")).toHaveCount(0);
  await expect(page.getByTestId("stage-search-audit")).not.toContainText("candidate_count");
  await page.getByTestId("stage-ranking-toggle").click();
  await expect(page.getByTestId("stage-ranking").locator("pre")).toHaveCount(0);
  await expect(page.getByTestId("stage-ranking-audit")).not.toContainText("batch_count");
  await expect(page.getByTestId("stage-ranking-audit")).not.toContainText("enriched_count");

  const details = page.getByTestId("run-details");
  await expect(page.getByTestId("run-details-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(details.getByTestId("system-log-audit")).toHaveCount(0);
  await page.getByTestId("run-details-toggle").click();

  await page.getByTestId("run-details-tab-process").click();
  for (const area of ["retrieval", "ranking", "enrichment"]) {
    const rows = page.getByTestId(`${area}-progress-audit`);
    await expect(rows).toBeVisible();
    await expect(rows.locator("pre")).toHaveCount(0);
  }
  await expect(page.getByTestId("retrieval-progress-audit")).not.toContainText("candidate_count");
  await expect(page.getByTestId("ranking-progress-audit")).not.toContainText("batch_count");
  await expect(page.getByTestId("enrichment-progress-audit")).not.toContainText("enriched_count");

  await expect(page.getByTestId("query-portfolio-audit")).toContainText("Direct evidence");
  await expect(page.getByTestId("run-details-tab-process")).toHaveAttribute("aria-selected", "true");

  await page.getByTestId("run-details-tab-log").click();
  await expect(page.getByTestId("system-log-audit")).toContainText("candidate_count");
  await page.getByTestId("run-details-tab-diagnostics").click();
  await expect(page.getByTestId("technical-audit-section")).not.toHaveAttribute("open", "");
  await expect(page.getByTestId("candidate-recovery-section")).not.toHaveAttribute("open", "");
  await page.getByTestId("technical-audit-toggle").click();
  await expect(page.getByTestId("technical-audit")).toContainText("candidate_queue");
});

test("full run identifier is kept out of the default primary layer", async ({ page }) => {
  await mockRun(page);
  await page.goto(`/runs/${runId}`);

  await expect(page.getByTestId("run-primary-summary")).not.toContainText(runId);
  await expect(page.locator(".search-form--readonly")).toContainText("OpenAlex");
  await expect(page.getByTestId("run-primary-summary").getByText("openalex", { exact: true })).toHaveCount(0);
  const details = page.getByTestId("run-details");
  const toggle = page.getByTestId("run-details-toggle");
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(details.getByText(runId, { exact: true })).toHaveCount(0);
  await toggle.click();
  await page.getByTestId("run-details-tab-diagnostics").click();
  await expect(details.getByText(runId, { exact: true })).toBeVisible();
});

test("minimum score has a dedicated localized all-scores option", async ({ page }) => {
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: run }));
  await page.route(`**/api/v1/runs/${runId}/results**`, (route) => route.fulfill({
    json: {
      results: [{ id: "paper-1", rank: 1, title: "Paper", authors: ["Author"], score: 9, metadata_status: "not_requested" }],
      next_cursor: null,
    },
  }));
  await page.goto(`/runs/${runId}/results`);

  await expect(page.getByLabel("Minimum score").locator("option").first()).toHaveText("All scores");
  await page.getByRole("button", { name: "中文" }).click();
  await expect(page.getByLabel("最低分数").locator("option").first()).toHaveText("全部分数");
});

test("Chinese diagnostics translate structured summaries and actions without parsing server prose", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("paperseek.locale", "zh"));
  await page.route("**/api/v1/sources", (route) => route.fulfill({
    json: { sources: [{ id: "openalex", label: "OpenAlex", default: true, status: "available", api_key: "not_required", capabilities: { filter: { mode: "none", label: "", options: [] }, citation_expansion: false }, credential: null }] },
  }));
  await page.route("**/api/v1/diagnostics", (route) => route.fulfill({
    json: {
      ok: false,
      status: "fail",
      summary: { pass: 1, warning: 0, fail: 1 },
      checks: [
        { id: "source.supported", status: "pass", severity: "info", ok: true, summary: "OpenAlex is supported.", actions: [], details: {} },
        { id: "llm.api_key", status: "fail", severity: "error", ok: false, summary: "An LLM credential is required unless provider is Ollama.", actions: ["Configure the LLM API key or choose Ollama for a local endpoint."], details: {} },
      ],
    },
  }));

  await page.goto("/search");
  await page.getByRole("button", { name: "检查配置" }).click();
  const result = page.getByTestId("diagnostic-result");
  await expect(page.getByTestId("diagnostic-status")).toHaveText("失败");
  await expect(result).toContainText("OpenAlex 可用");
  await expect(result).toContainText("使用非 Ollama 提供商时必须填写 LLM 凭据");
  await expect(result).toContainText("填写 LLM API 密钥，或选择 Ollama 本地端点");
  await expect(result).not.toContainText("An LLM credential is required");
});

test("provider, source and internal values use bilingual display names while keeping API values", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("paperseek.locale", "zh"));
  await page.route("**/api/v1/sources", (route) => route.fulfill({
    json: { sources: [
      { id: "openalex", label: "OpenAlex", default: true, status: "available", api_key: "not_required", capabilities: { filter: { mode: "none", label: "", options: [] }, citation_expansion: false }, credential: null },
      { id: "paperhub", label: "Computer science top conferences", default: false, status: "available", api_key: "not_required", capabilities: { filter: { mode: "text", label: "Computer science field/context hint", options: [] }, citation_expansion: false }, credential: null },
    ] },
  }));

  await page.goto("/search");
  const source = page.getByLabel("数据源");
  await expect(source.locator('option[value="paperhub"]')).toHaveText("计算机顶会");
  await page.getByText("高级设置", { exact: true }).click();
  const embedding = page.getByLabel("Embedding 提供商");
  const reranker = page.getByLabel("Reranker 提供商");
  await expect(embedding.locator('option[value="local"]')).toHaveText("本地");
  await expect(embedding.locator('option[value="cstcloud"]')).toHaveText("CSTCloud");
  await expect(embedding.locator('option[value="custom"]')).toHaveText("自定义");
  await expect(reranker.locator('option[value=""]')).toHaveText("关闭");
  await expect(reranker.locator('option[value="custom"]')).toHaveText("自定义");
  const llmProvider = page.getByText("提供商", { exact: true }).locator("..").locator("select");
  await expect(llmProvider.locator('option[value="custom"]')).toHaveText("自定义");
  await embedding.selectOption("custom");
  await expect(embedding).toHaveValue("custom");

  await page.getByRole("button", { name: "EN" }).click();
  await expect(page.getByLabel("Data Source").locator('option[value="paperhub"]')).toHaveText("Computer science top conferences");
  await expect(page.getByLabel("Embedding Provider").locator('option[value="local"]')).toHaveText("Local");
  await expect(page.getByLabel("Embedding Provider").locator('option[value="custom"]')).toHaveText("Custom");
});

test("history keeps run identifiers and raw durable events in a folded technical disclosure", async ({ page }) => {
  const warningCodes = [
    "retrieval_partial",
    "retrieval_lane_failed:impact",
    "query_portfolio_failed:repair",
    "citation_expansion_failed_base_candidates_retained",
    "abstract_enrichment_failed:10.1000/example",
    "ranking_partial_failure_local_order_retained",
    "future_warning_code",
  ];
  await page.route("**/api/v1/history**", (route) => route.fulfill({ json: { items: [run], next_cursor: null } }));
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: { ...run, error_code: "ranking_failed", warnings: warningCodes } }));
  await page.route(`**/api/v1/runs/${runId}/events`, (route) => route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    body: `id: 6\ndata: ${JSON.stringify({ ...events[5], payload: { ...events[5].payload, warnings: warningCodes } })}\n\n`,
  }));

  await page.goto("/history");
  await page.getByRole("button", { name: /Release UX regression audit/ }).click();
  const detail = page.getByTestId("history-detail");
  const primary = page.getByTestId("history-primary-detail");
  await expect(primary).toContainText("OpenAlex");
  await expect(primary.getByText("openalex", { exact: true })).toHaveCount(0);
  await expect(primary).not.toContainText(runId);
  await expect(primary).toContainText("Ranking failed.");
  await expect(primary).not.toContainText("ranking_failed");
  await expect(primary).toContainText("Retrieval completed with partial coverage.");
  await expect(primary).toContainText("Some source retrieval lanes were degraded.");
  await expect(primary).toContainText("A query variant was repaired or skipped.");
  await expect(primary).toContainText("Citation expansion was only partially available.");
  await expect(primary).toContainText("Some abstracts could not be completed.");
  await expect(primary).toContainText("Some papers were not scored; unscored items are kept.");
  await expect(primary).toContainText("The run completed with an additional warning.");
  for (const code of warningCodes) await expect(primary).not.toContainText(code);
  const audit = page.getByTestId("history-run-details");
  await expect(page.getByTestId("history-run-details-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(audit.getByText(runId, { exact: true })).toHaveCount(0);
  await page.getByTestId("history-run-details-toggle").click();
  await expect(audit.getByTestId("system-log-audit")).toContainText("ranking.completed");
  await expect(audit.getByTestId("system-log-audit")).toContainText("candidate_count");
  for (const code of warningCodes) await expect(audit.getByTestId("system-log-audit")).toContainText(code);
  await page.getByTestId("history-run-details-tab-diagnostics").click();
  await expect(audit.getByText(runId, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "中文" }).click();
  await expect(primary).toContainText("部分数据源召回通道已降级。");
  await expect(primary).toContainText("部分摘要未能补全。");
  await expect(primary).toContainText("部分论文未完成评分，未评分项已保留。");
  await expect(primary).toContainText("运行包含一项额外警告。");
});

test("run warning projection is bilingual while the folded system log preserves machine codes", async ({ page }) => {
  const warningCodes = ["retrieval_lane_failed:impact", "abstract_enrichment_failed:10.1000/example", "future_warning_code"];
  const warnedRun = { ...run, warnings: warningCodes };
  const warningEvents = events.map((event, index) => index === events.length - 1
    ? { ...event, payload: { ...event.payload, warnings: warningCodes } }
    : event);
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: warnedRun }));
  await page.route(`**/api/v1/runs/${runId}/events**`, (route) => route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    body: warningEvents.map((event) => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`).join(""),
  }));
  await page.route(`**/api/v1/runs/${runId}/audit**`, (route) => route.fulfill({ json: { query_portfolio: [], loop_decisions: [], candidate_queue: {}, candidate_lifecycle: {}, recovery: {} } }));

  await page.goto(`/runs/${runId}`);
  const primary = page.getByTestId("run-primary-summary");
  await expect(primary).toContainText("Some source retrieval lanes were degraded.");
  await expect(primary).toContainText("Some abstracts could not be completed.");
  await expect(primary).toContainText("The run completed with an additional warning.");
  for (const code of warningCodes) await expect(primary).not.toContainText(code);
  await page.getByRole("button", { name: "中文" }).click();
  await expect(primary).toContainText("部分数据源召回通道已降级。");
  await expect(primary).toContainText("部分摘要未能补全。");
  await page.getByTestId("run-details-toggle").click();
  for (const code of warningCodes) await expect(page.getByTestId("system-log-audit")).toContainText(code);
});
