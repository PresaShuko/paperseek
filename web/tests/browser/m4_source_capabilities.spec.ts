import { expect, test } from "@playwright/test";


const runId = "77777777-7777-4777-8777-777777777777";
const question = "How do capability-driven literature filters affect retrieval?";
const nativeOption = (id: string, label: string, domain: string) => ({ id, label, domain });
const credentials = {
  openalex: ["recommended", "OpenAlex API Key", "Get OpenAlex API key", "https://openalex.org/settings/api"],
  semanticscholar: ["optional", "Semantic Scholar API Key", "Request Semantic Scholar API key", "https://www.semanticscholar.org/product/api#api-key-form"],
  pubmed: ["optional", "PubMed API Key", "Get NCBI API key", "https://www.ncbi.nlm.nih.gov/books/NBK25497/"],
  wos: ["required", "Web of Science Starter API Key", "Register Web of Science Starter application", "https://developer.clarivate.com/apis/wos-starter"],
  googlescholar: ["required", "Serper API Key", "Get Serper API key", "https://serper.dev/"],
} as const;
const source = (
  id: string,
  label: string,
  mode: "native" | "text" | "none",
  filterLabel: string,
  options: Array<{ id: string; label: string; domain: string }> = [],
  citationExpansion = false,
) => {
  const credential = credentials[id as keyof typeof credentials];
  return ({
  id,
  label,
  default: id === "openalex",
  status: id === "wos" ? "temporarily_unavailable" : id === "openalex" ? "default" : "supported",
  api_key: credential?.[0] || "not_required",
  credential: credential ? {
    input_label: credential[1],
    guidance_label: credential[2],
    guidance_url: credential[3],
  } : null,
  capabilities: {
    citation_expansion: citationExpansion,
    filter: { mode, label: filterLabel, options },
  },
  });
};

const sources = [
  source("openalex", "OpenAlex", "native", "OpenAlex Field", [
    nativeOption("17", "Computer Science", "Physical Sciences"),
    nativeOption("22", "Engineering", "Physical Sciences"),
  ], true),
  source("arxiv", "arXiv", "native", "arXiv Category", [
    nativeOption("cs.AI", "Artificial Intelligence", "Computer Science"),
  ]),
  source("crossref", "Crossref", "none", ""),
  source("semanticscholar", "Semantic Scholar", "text", "Field/context hint"),
  source("pubmed", "PubMed", "text", "Biomedical field/context hint"),
  source("wos", "Web of Science Starter", "native", "Web of Science Category", [
    nativeOption("Computer Science, Artificial Intelligence", "Computer Science, Artificial Intelligence", "Web of Science Category"),
  ]),
  source("googlescholar", "Google Scholar (Serper)", "text", "Google Scholar field/context hint"),
  source("paperhub", "Computer science top conferences", "text", "Computer science field/context hint"),
];

test("source capabilities drive native, text, none and citation controls", async ({ page }) => {
  let submittedBody: Record<string, unknown> | undefined;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/sources") {
      await route.fulfill({ json: { sources } });
    } else if (path === "/api/v1/runs" && request.method() === "POST") {
      submittedBody = request.postDataJSON();
      await route.fulfill({ status: 202, json: {
        id: runId,
        question,
        source: "openalex",
        status: "completed_with_warnings",
        current_step: "workflow.completed",
        last_event_sequence: 0,
        result_count: 0,
        warnings: ["retrieval_rerank_failed_rrf_order_retained"],
        created_at: "2026-08-10T00:00:00Z",
        finished_at: "2026-08-10T00:00:01Z",
      } });
    } else if (path === `/api/v1/runs/${runId}`) {
      await route.fulfill({ json: {
        id: runId,
        question,
        source: "openalex",
        status: "completed_with_warnings",
        current_step: "workflow.completed",
        last_event_sequence: 0,
        result_count: 0,
        warnings: ["retrieval_rerank_failed_rrf_order_retained"],
        created_at: "2026-08-10T00:00:00Z",
        finished_at: "2026-08-10T00:00:01Z",
      } });
    } else if (path === `/api/v1/runs/${runId}/events`) {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });

  await page.goto("/search");
  const sourceSelect = page.getByLabel("Data Source");
  await expect(sourceSelect.locator("option")).toHaveCount(8);
  for (const descriptor of sources) {
    await sourceSelect.selectOption(descriptor.id);
    await expect(sourceSelect).toHaveValue(descriptor.id);
  }
  await sourceSelect.selectOption("openalex");

  await page.getByText("Advanced settings", { exact: true }).click();
  await expect(page.getByLabel("Embedding Provider")).toHaveValue("local");
  await expect(page.getByLabel("Reranker Provider")).toHaveValue("");
  await page.getByLabel("Embedding Provider").selectOption("openai");
  await expect(page.getByLabel("Embedding Model")).toHaveValue("text-embedding-3-large");
  await expect(page.getByLabel("Embedding Base URL")).toHaveValue("https://api.openai.com/v1");
  await page.getByLabel("Embedding API Key").fill("ephemeral-embedding-key");
  await page.getByLabel("Reranker Provider").selectOption("nvidia");
  await expect(page.getByLabel("Reranker Model")).toHaveValue("nv-rerank-qa-mistral-4b:1");
  await page.getByLabel("Reranker API Key").fill("ephemeral-reranker-key");

  for (const [sourceId, metadata] of Object.entries(credentials)) {
    await sourceSelect.selectOption(sourceId);
    await expect(page.getByLabel(metadata[1])).toBeVisible();
    await expect(page.getByTestId("source-credential-requirement")).toHaveText({
      recommended: "Recommended",
      optional: "Optional",
      required: "Required",
    }[metadata[0]]);
    await expect(page.getByRole("link", { name: metadata[2] })).toHaveAttribute("href", metadata[3]);
    await expect(page.locator('[data-testid="source-credential"]')).toHaveCount(1);
  }
  for (const sourceId of ["arxiv", "crossref", "paperhub"]) {
    await sourceSelect.selectOption(sourceId);
    await expect(page.locator('[data-testid="source-credential"]')).toHaveCount(0);
  }
  await sourceSelect.selectOption("openalex");

  await expect(page.getByRole("group", { name: "Fields of study" })).toBeVisible();
  await expect(page.getByLabel("Computer Science", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Expand Citations")).toBeVisible();

  await sourceSelect.selectOption("wos");
  await expect(page.getByRole("group", { name: "Web of Science Category" })).toBeVisible();
  await expect(page.getByLabel("Computer Science, Artificial Intelligence", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Expand Citations")).toHaveCount(0);

  await sourceSelect.selectOption("googlescholar");
  await expect(page.getByLabel("Google Scholar (Serper) · Field/context hint")).toBeVisible();
  await sourceSelect.selectOption("paperhub");
  await expect(page.getByLabel("Computer science top conferences · Field/context hint")).toBeVisible();

  await sourceSelect.selectOption("crossref");
  await expect(page.locator('[data-testid="source-filter"]')).toHaveCount(0);

  await sourceSelect.selectOption("openalex");
  await page.getByLabel("Computer Science", { exact: true }).check();
  await page.getByLabel("Engineering", { exact: true }).check();
  await page.getByLabel("OpenAlex API Key").fill("ephemeral-source-key");
  await page.getByLabel("Research Question").fill(question);
  await page.getByRole("button", { name: "Run Search" }).click();
  await expect(page).toHaveURL(`/runs/${runId}`);
  await expect(page).not.toHaveURL(/ephemeral-source-key/);
  await expect(page).not.toHaveURL(/ephemeral-(embedding|reranker)-key/);
  await expect(page.getByText("External reranking failed; fused retrieval order was retained.")).toBeVisible();
  expect(submittedBody).toMatchObject({
    question,
    source: "openalex",
    search_budget: "fast",
    field_ids: ["17", "22"],
    field_hint: "",
    citation_enabled: true,
    retrieval: {
      embedding: {
        provider: "openai",
        model: "text-embedding-3-large",
        base_url: "https://api.openai.com/v1",
      },
      reranker: {
        provider: "nvidia",
        model: "nv-rerank-qa-mistral-4b:1",
        base_url: "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking",
      },
    },
    credentials: {
      source: { api_key: "ephemeral-source-key" },
      embedding: { api_key: "ephemeral-embedding-key" },
      reranker: { api_key: "ephemeral-reranker-key" },
    },
  });
  expect(submittedBody).not.toHaveProperty("field");

  await page.goBack();
  await expect(page).toHaveURL("/search");
  await expect(page.getByLabel("OpenAlex API Key")).toHaveValue("");
  await expect(page.getByLabel("Embedding API Key")).toHaveValue("");
  await expect(page.getByLabel("Reranker API Key")).toHaveValue("");
});
