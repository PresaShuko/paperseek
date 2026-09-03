import { expect, test } from "@playwright/test";


const sources = [
  {
    id: "openalex",
    label: "OpenAlex",
    api_key: "recommended",
    status: "default",
    default: true,
    credential: {
      input_label: "OpenAlex API Key",
      guidance_label: "Get OpenAlex API key",
      guidance_url: "https://openalex.org/settings/api",
    },
    capabilities: {
      citation_expansion: true,
      filter: { mode: "native", label: "OpenAlex Field", options: [] },
    },
  },
  {
    id: "arxiv",
    label: "arXiv",
    api_key: "not_required",
    status: "supported",
    default: false,
    credential: null,
    capabilities: {
      citation_expansion: false,
      filter: { mode: "native", label: "arXiv Category", options: [] },
    },
  },
];

test("configuration diagnostics exposes pass, warning and fail without leaking credentials", async ({ page }) => {
  const requests: Array<Record<string, any>> = [];
  let submitted: Record<string, any> | undefined;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/sources") {
      await route.fulfill({ json: { sources } });
      return;
    }
    if (path === "/api/v1/diagnostics" && request.method() === "POST") {
      const body = request.postDataJSON() as Record<string, any>;
      requests.push(body);
      const provider = body.llm.provider;
      const source = body.source;
      const status = provider === "openai" ? "fail" : source === "openalex" ? "warning" : "pass";
      await route.fulfill({ json: {
        ok: status !== "fail",
        status,
        checks: [{
          id: status === "fail" ? "llm.api_key" : "source.credentials",
          status,
          severity: status === "fail" ? "error" : status,
          summary: status === "fail" ? "LLM credential is required." : "Configuration was checked.",
          actions: status === "pass" ? [] : ["Review the selected configuration."],
          details: {},
          ok: status !== "fail",
        }],
        summary: { pass: status === "pass" ? 1 : 0, warning: status === "warning" ? 1 : 0, fail: status === "fail" ? 1 : 0 },
      } });
      return;
    }
    if (path === "/api/v1/runs" && request.method() === "POST") {
      submitted = request.postDataJSON();
      await route.fulfill({ status: 202, json: {
        id: "88888888-8888-4888-8888-888888888888",
        question: submitted!.question,
        source: submitted!.source,
        status: "queued",
        created_at: "2026-08-12T00:00:00Z",
      } });
      return;
    }
    await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto("/search");
  await page.getByText("Provider", { exact: true }).locator("..").locator("select").selectOption("ollama");
  await page.getByLabel("API Key", { exact: true }).fill("diagnostics-llm-secret");
  await page.getByRole("button", { name: "Check Configuration" }).click();
  await expect(page.getByTestId("diagnostic-status")).toHaveText("Warning");
  await expect(page.getByText("Configure the source credential or choose a source that does not require one.")).toBeVisible();

  await page.getByLabel("Data Source").selectOption("arxiv");
  await page.getByRole("button", { name: "Check Configuration" }).click();
  await expect(page.getByTestId("diagnostic-status")).toHaveText("Pass");

  await page.getByText("Provider", { exact: true }).locator("..").locator("select").selectOption("openai");
  await page.getByRole("button", { name: "Check Configuration" }).click();
  await expect(page.getByTestId("diagnostic-status")).toHaveText("Fail");
  await expect(page.getByText("An LLM credential is required unless the provider is Ollama.")).toBeVisible();

  expect(requests).toHaveLength(3);
  expect(requests[0]).toMatchObject({
    source: "openalex",
    llm: { provider: "ollama", api_type: "openai_chat", model: "qwen3:8b" },
    credentials: { llm: { api_key: "diagnostics-llm-secret" } },
  });
  expect(page.url()).not.toContain("diagnostics-llm-secret");
  expect(await page.locator("body").innerText()).not.toContain("diagnostics-llm-secret");

  await page.getByText("Provider", { exact: true }).locator("..").locator("select").selectOption("custom");
  await page.getByLabel("Model", { exact: true }).fill("loopback-model");
  await page.getByText("Advanced settings", { exact: true }).click();
  await page.getByLabel("Base URL", { exact: true }).fill("http://127.0.0.1:11434/v1");
  await page.getByLabel("API Key", { exact: true }).fill("custom-browser-secret");
  await page.getByRole("button", { name: "Check Configuration" }).click();
  await expect(page.getByTestId("diagnostic-status")).toHaveText("Pass");
  await page.getByLabel("Research Question").fill("Custom loopback submission");
  await page.getByRole("button", { name: "Run Search" }).click();
  await expect(page).toHaveURL(/\/runs\/88888888-8888-4888-8888-888888888888$/);
  expect(submitted).toMatchObject({
    llm: {
      provider: "custom",
      api_type: "openai_chat",
      model: "loopback-model",
      base_url: "http://127.0.0.1:11434/v1",
    },
    credentials: { llm: { api_key: "custom-browser-secret" } },
  });
  expect(page.url()).not.toContain("custom-browser-secret");
});
