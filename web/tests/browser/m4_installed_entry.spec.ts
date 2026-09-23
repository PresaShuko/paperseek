import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";


test("installed Community entry serves Vue and records an explicit no-key failure", async ({ page }) => {
  test.skip(process.env.PAPERSEEK_REAL_ENTRY !== "1", "Requires a real local paperseek serve process.");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "PaperSeek" })).toBeVisible();
  await expect(page.getByLabel("Data Source")).toHaveValue("openalex");
  await expect(page.getByLabel("Data Source").locator("option")).toHaveCount(8);
  await expect(page.getByRole("group", { name: "Fields of study" })).toBeVisible();
  await page.getByTestId("field-selector-toggle").click();
  await expect(page.getByLabel("Computer Science", { exact: true })).toBeVisible();
  await page.getByTestId("field-selector-close").click();
  await expect(page.getByLabel("Expand Citations")).toBeVisible();
  await page.getByText("Advanced settings", { exact: true }).click();
  await expect(page.getByLabel("Embedding Provider")).toHaveValue("local");
  await expect(page.getByLabel("Reranker Provider")).toHaveValue("");
  await page.getByLabel("Embedding Provider").selectOption("openai");
  await expect(page.getByLabel("Embedding Model")).toHaveValue("text-embedding-3-large");
  await page.getByLabel("Reranker Provider").selectOption("nvidia");
  await expect(page.getByLabel("Reranker Model")).toHaveValue("nv-rerank-qa-mistral-4b:1");
  await page.getByLabel("Embedding Provider").selectOption("local");
  await page.getByLabel("Reranker Provider").selectOption("");
  await expect(page.getByLabel("OpenAlex API Key")).toBeVisible();
  await expect(page.getByRole("link", { name: "Get OpenAlex API key" })).toHaveAttribute(
    "href",
    "https://openalex.org/settings/api",
  );
  await page.getByLabel("Data Source").selectOption("semanticscholar");
  await expect(page.getByLabel("Semantic Scholar API Key")).toBeVisible();
  await expect(page.getByRole("link", { name: "Request Semantic Scholar API key" })).toBeVisible();
  await page.getByLabel("Data Source").selectOption("pubmed");
  await expect(page.getByLabel("PubMed API Key")).toBeVisible();
  await expect(page.getByRole("link", { name: "Get NCBI API key" })).toBeVisible();
  await page.getByLabel("Data Source").selectOption("wos");
  await expect(page.getByRole("group", { name: "Web of Science Category" })).toBeVisible();
  await expect(page.getByLabel("Expand Citations")).toHaveCount(0);
  await expect(page.getByLabel("Web of Science Starter API Key")).toBeVisible();
  await page.getByLabel("Data Source").selectOption("googlescholar");
  await expect(page.getByLabel("Google Scholar (Serper) · Field/context hint")).toBeVisible();
  await expect(page.getByLabel("Serper API Key")).toBeVisible();
  await expect(page.getByRole("link", { name: "Get Serper API key" })).toBeVisible();
  await page.getByLabel("Data Source").selectOption("arxiv");
  await expect(page.locator('[data-testid="source-credential"]')).toHaveCount(0);
  const llmProvider = page.getByText("Provider", { exact: true }).locator("..").locator("select");
  await llmProvider.selectOption("ollama");
  await page.getByRole("button", { name: "Check Configuration" }).click();
  await expect(page.getByTestId("diagnostic-status")).toHaveText("Pass");
  await llmProvider.selectOption("openai");
  await page.getByRole("button", { name: "Check Configuration" }).click();
  await expect(page.getByTestId("diagnostic-status")).toHaveText("Fail");
  await expect(page.getByText("An LLM credential is required unless the provider is Ollama.")).toBeVisible();
  await page.getByLabel("Data Source").selectOption("openalex");

  await page.getByRole("button", { name: "中文" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByLabel("研究问题")).toBeVisible();
  await page.getByRole("button", { name: "EN" }).click();

  const question = `M4 installed no-key boundary ${Date.now()}`;
  await page.getByLabel("Research Question").fill(question);
  await page.getByRole("button", { name: "Run Search" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Failed", { timeout: 15_000 });
  const failedRunUrl = page.url();
  expect(failedRunUrl).toMatch(/\/runs\/[0-9a-f-]+$/);

  await page.reload();
  await expect(page.getByTestId("run-status")).toHaveText("Failed", { timeout: 15_000 });
  await page.goto(`${failedRunUrl}/results`);
  await expect(page.getByRole("heading", { name: question, exact: true })).toBeVisible();

  await page.goto("/history");
  await expect(page.getByRole("button", { name: new RegExp(question) })).toBeVisible();

  const completed = await page.evaluate(async () => {
    const response = await fetch("/api/v1/history");
    const payload = await response.json();
    return payload.items.find((item: { status: string }) => item.status === "completed") || null;
  });
  expect(completed).not.toBeNull();
  await page.goto(`/runs/${completed.id}`);
  await page.getByTestId("stage-query-toggle").click();
  await expect(page.getByTestId("stage-query-audit")).toContainText("Current query");
  await page.getByTestId("stage-ranking-toggle").click();
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("Multi-lane recall");
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("LLM re-ranking");
  await page.getByTestId("stage-results-toggle").click();
  await expect(page.getByTestId("stage-results-audit")).toContainText("Results");
  await page.getByTestId("stage-search-toggle").click();
  await page.getByTestId("stage-search-portfolio-toggle").click();
  await expect(page.getByTestId("query-portfolio-audit")).toContainText("No query portfolio records.");
  await page.getByTestId("stage-search-audit-toggle").click();
  await expect(page.getByTestId("technical-audit")).toContainText('"action": "accept"');
  await expect(page.getByTestId("technical-audit")).toContainText("candidate_queue");
  await page.getByTestId("stage-ranking-toggle").click();
  await page.getByTestId("stage-ranking-audit-toggle").click();
  await expect(page.getByTestId("candidate-recovery-audit")).toContainText('"ledger_candidates": 1');
  await expect(page.getByTestId("candidate-recovery-audit")).toContainText('"total": 0');
  await page.reload();
  await page.getByTestId("stage-query-toggle").click();
  await expect(page.getByTestId("stage-query-audit")).toContainText("Current query");
  await page.getByTestId("stage-search-toggle").click();
  await page.getByTestId("stage-search-audit-toggle").click();
  await expect(page.getByTestId("technical-audit")).toContainText('"action": "accept"');
  await page.goto(`/runs/${completed.id}/results`);
  await expect(page.getByRole("heading", { name: completed.question, exact: true })).toBeVisible();
  await page.goto(`/runs/${completed.id}/citation-map`);
  await expect(page.getByRole("heading", { name: completed.question, exact: true })).toBeVisible();
});

test("installed Community Stop reaches cancelling and cancelled through the real API", async ({ page }) => {
  const runId = process.env.PAPERSEEK_REAL_STOP_RUN_ID;
  const database = process.env.PAPERSEEK_REAL_STOP_DATABASE;
  const python = process.env.PAPERSEEK_REAL_STOP_PYTHON;
  test.skip(
    process.env.PAPERSEEK_REAL_ENTRY !== "1" || !runId || !database || !python,
    "Requires a real installed server and a claimed fixture run.",
  );

  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status")).toHaveText("Running");
  const stop = page.getByRole("button", { name: "Stop" });
  await expect(stop).toBeEnabled();
  await stop.click();
  await expect(page.getByTestId("run-status")).toHaveText("Cancelling");
  // Stop leaves the page once cancellation is in flight (§5.1), not a permanent disabled button.
  await expect(stop).toHaveCount(0);

  const completeCancel = [
    "from pathlib import Path",
    "import sys",
    "from paperseek_app.models import LeaseToken",
    "from paperseek_community.persistence import SQLiteRunUnitOfWork",
    "uow = SQLiteRunUnitOfWork(Path(sys.argv[1]))",
    "run = uow.get_run(sys.argv[2])",
    "lease = LeaseToken(run_id=run.id, owner_id=run.lease_owner, lease_generation=run.lease_generation, expires_at=run.lease_expires_at)",
    "uow.complete_cancel(lease)",
    "uow.close()",
  ].join("; ");
  execFileSync(python!, ["-c", completeCancel, database!, runId!], {
    env: { ...process.env, PYTHONNOUSERSITE: "1" },
    stdio: "pipe",
  });

  await expect(page.getByTestId("run-status")).toHaveText("Cancelled", { timeout: 10_000 });
  await expect(page.getByTestId("stage-results")).not.toHaveAttribute("data-state", "complete");
  await expect(stop).toHaveCount(0);
});
