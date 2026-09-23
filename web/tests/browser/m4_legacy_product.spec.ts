import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";


const fixtureRoot = resolve(import.meta.dirname, "../../../tests/fixtures/golden_search");
const finalResult = JSON.parse(readFileSync(resolve(fixtureRoot, "final_result.json"), "utf8"));
const citationMap = JSON.parse(readFileSync(resolve(fixtureRoot, "citation_map.json"), "utf8"));
const csvExport = readFileSync(resolve(fixtureRoot, "export.csv"));
const runId = "11111111-1111-4111-8111-111111111111";
const question = "How do transparent AI decision systems affect accountability in public agencies?";

const sources = [
  ["openalex", "OpenAlex"],
  ["arxiv", "arXiv"],
  ["semanticscholar", "Semantic Scholar"],
  ["pubmed", "PubMed"],
  ["googlescholar", "Google Scholar"],
  ["paperhub", "Computer science top conferences"],
  ["crossref", "Crossref"],
  ["wos", "Web of Science Starter"],
].map(([id, label], index) => ({
  id,
  label,
  default: index === 0,
  status: id === "wos" ? "temporarily_unavailable" : "available",
  api_key: id === "wos" || id === "googlescholar" ? "required" : "not_required",
  capabilities: {
    citation_expansion: id === "openalex",
    filter: {
      mode: ["openalex", "arxiv", "wos"].includes(id) ? "native" : "text",
      label: `${label} filter`,
      options: [],
    },
  },
}));

const run = {
  id: runId,
  question,
  source: "openalex",
  status: "completed",
  current_step: "workflow.completed",
  last_event_sequence: 8,
  result_count: finalResult.ranked.length,
  warnings: [],
  created_at: "2026-08-10T00:00:00Z",
  finished_at: "2026-08-10T00:01:00Z",
};

const stages = [
  [1, "query.started", "query.analyze"],
  [2, "query.completed", "query.plan"],
  [3, "retrieval.started", "retrieve.sources"],
  [4, "retrieval.completed", "retrieve.fuse"],
  [5, "ranking.started", "rank.results"],
  [6, "ranking.completed", "rank.results"],
  [7, "final.started", "final.assemble"],
  [8, "workflow.completed", "workflow.completed"],
].map(([sequence, event_type, stage]) => ({
  run_id: runId,
  sequence,
  event_type,
  stage,
  occurred_at: "2026-08-10T00:00:00Z",
  schema_version: 1,
  payload: {},
}));

function sseBody(): string {
  return stages.map((event) =>
    `id: ${event.sequence}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`,
  ).join("");
}

test("Vue preserves the four-stage bilingual search, result, graph, export and history flow", async ({ page }) => {
  let submittedBody: Record<string, unknown> | undefined;
  let idempotencyKey = "";

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/sources") {
      await route.fulfill({ json: { sources } });
    } else if (path === "/api/v1/runs" && request.method() === "POST") {
      submittedBody = request.postDataJSON();
      idempotencyKey = request.headers()["idempotency-key"] || "";
      await route.fulfill({ status: 202, json: { ...run, status: "queued" } });
    } else if (path === `/api/v1/runs/${runId}/events`) {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: sseBody() });
    } else if (path === `/api/v1/runs/${runId}/results`) {
      await route.fulfill({ json: { results: finalResult.ranked, next_cursor: null } });
    } else if (path === `/api/v1/runs/${runId}/citation-map`) {
      await route.fulfill({ json: citationMap });
    } else if (path === `/api/v1/runs/${runId}/export`) {
      await route.fulfill({
        headers: { "Content-Disposition": "attachment; filename=paperseek-results.csv" },
        contentType: "text/csv; charset=utf-8",
        body: csvExport,
      });
    } else if (path === "/api/v1/history") {
      await route.fulfill({ json: { items: [run], next_cursor: null } });
    } else if (path === `/api/v1/runs/${runId}`) {
      await route.fulfill({ json: run });
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "PaperSeek" })).toBeVisible();
  await expect(page.getByLabel("Research Question")).toBeVisible();
  await expect(page.getByLabel("Data Source")).toHaveValue("openalex");
  await expect(page.getByLabel("Fast")).toBeChecked();
  await expect(page.getByRole("navigation", { name: "Workspace section" })).toBeVisible();
  const llmProvider = page.getByText("Provider", { exact: true }).locator("..").locator("select");
  await expect(llmProvider.locator('option[value="cstcloud"]')).toHaveCount(1);
  await expect(llmProvider.locator('option[value="nvidia"]')).toHaveCount(1);
  await expect(llmProvider.locator('option[value="openrouter"]')).toHaveCount(1);
  await llmProvider.selectOption("modelscope");
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue("Qwen/Qwen3-235B-A22B-Instruct-2507");
  await llmProvider.selectOption("openai");

  await page.getByRole("button", { name: "中文" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByLabel("研究问题")).toBeVisible();
  await page.getByRole("button", { name: "EN" }).click();

  await page.getByLabel("Research Question").fill(question);
  await page.getByLabel("Data Source").selectOption("openalex");
  await page.getByRole("button", { name: "Run Search" }).click();
  await expect(page.getByTestId("stage-results").locator(".badge").first()).toHaveText("Complete");
  expect(submittedBody).toMatchObject({ question, source: "openalex", search_budget: "fast" });
  expect(idempotencyKey).not.toBe("");

  for (const key of ["query", "search", "ranking", "results"]) {
    await expect(page.getByTestId(`stage-${key}`)).toBeVisible();
  }
  await expect(page.getByTestId("stage-results")).toHaveAttribute("data-state", "complete");

  await page.getByRole("link", { name: "Results", exact: true }).click();
  await expect(page.getByRole("heading", { name: finalResult.ranked[0].title })).toBeVisible();
  const exportLink = page.getByRole("link", { name: "Export all CSV" });
  await expect(exportLink).toHaveAttribute("href", new RegExp(`/api/v1/runs/${runId}/export\\?format=csv$`));
  const exportResult = await page.evaluate(async (href) => {
    const response = await fetch(href);
    return {
      disposition: response.headers.get("content-disposition"),
      byteLength: (await response.arrayBuffer()).byteLength,
    };
  }, await exportLink.getAttribute("href") || "");
  expect(exportResult.disposition).toContain("paperseek-results.csv");
  expect(exportResult.byteLength).toBe(csvExport.byteLength);

  await page.getByRole("link", { name: "Citation Map", exact: true }).click();
  await expect(page.getByText(`${citationMap.nodes.length} nodes`)).toBeVisible();
  await page.getByTestId("citation-text-list").getByText("Text list").click();
  await expect(page.getByRole("button", { name: citationMap.nodes[0].title, exact: true })).toBeVisible();

  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("button", { name: new RegExp(question) })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(question) }).click();
  await expect(page.getByTestId("history-detail")).toContainText(question);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("navigation", { name: "Workspace section" })).toBeVisible();
});
