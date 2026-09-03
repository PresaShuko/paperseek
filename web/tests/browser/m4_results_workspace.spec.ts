import { expect, test } from "@playwright/test";

const runId = "66666666-6666-4666-8666-666666666666";
const run = {
  id: runId,
  question: "result workspace behavior",
  source: "openalex",
  status: "completed",
  result_count: 4,
  warnings: [],
  created_at: "2026-08-12T00:00:00Z",
  finished_at: "2026-08-12T00:01:00Z",
};

const papers = [
  {
    rank: 1,
    title: "Alpha complete record",
    authors: ["Ada Author", "Ben Writer"],
    publish_year: 2024,
    venue: "Journal A",
    abstract: "Alpha abstract about resilient retrieval.",
    score: 8.1,
    reasoning: "Strong direct evidence.",
    citations: "7",
    doi: "10.1000/alpha",
    url: "https://example.test/alpha",
    pdf_url: "https://example.test/alpha.pdf",
    provider: "openalex",
    metadata_status: "complete",
  },
  {
    rank: 2,
    title: "Beta sparse record",
    authors: [],
    publish_year: 2021,
    score: 9.2,
    citations: "2",
    provider: "openalex",
    metadata_status: "unavailable",
  },
  {
    rank: 3,
    title: "Gamma cited record",
    authors_text: "Grace Researcher",
    publish_year: 2025,
    abstract: "Gamma abstract.",
    score: 7.4,
    citations: "42",
    doi: "10.1000/gamma",
    url: "https://example.test/gamma",
    provider: "crossref",
    metadata_status: "degraded",
  },
  {
    rank: 4,
    title: "Delta PDF record",
    authors: ["Dana Scholar"],
    publish_year: 2023,
    score: 8.8,
    citations: "11",
    pdf_url: "https://example.test/delta.pdf",
    provider: "arxiv",
    metadata_status: "complete",
  },
];

test("results workspace loads cursors, filters, sorts, selects and renders sparse metadata safely", async ({ page }) => {
  const requestedCursors: Array<string | null> = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === `/api/v1/runs/${runId}`) {
      await route.fulfill({ json: run });
    } else if (url.pathname === `/api/v1/runs/${runId}/results`) {
      const cursor = url.searchParams.get("cursor");
      requestedCursors.push(cursor);
      await route.fulfill({
        json: cursor === "page-2"
          ? { results: papers.slice(2), next_cursor: null }
          : { results: papers.slice(0, 2), next_cursor: "page-2" },
      });
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });

  await page.goto(`/runs/${runId}/results`);
  await expect(page.getByRole("heading", { name: papers[0].title })).toBeVisible();
  await expect(page.getByText(papers[2].title)).toHaveCount(0);
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByRole("heading", { name: papers[2].title })).toBeVisible();
  expect(requestedCursors).toEqual([null, "page-2"]);

  await page.getByLabel("Search results").fill("Gamma");
  await expect(page.getByTestId("result-card")).toHaveCount(1);
  await page.getByRole("button", { name: "Select all shown" }).click();
  await expect(page.getByTestId("selection-count")).toHaveText("1 selected");
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(page.getByTestId("selection-count")).toHaveText("0 selected");

  await page.getByLabel("Search results").fill("");
  await page.getByLabel("Availability").selectOption("pdf");
  await expect(page.getByTestId("result-card")).toHaveCount(2);
  await page.getByLabel("Availability").selectOption("all");
  await page.getByLabel("Minimum score").selectOption("8");
  await expect(page.getByTestId("result-card")).toHaveCount(3);
  await page.getByLabel("Minimum score").selectOption("all");
  await page.getByLabel("Sort results").selectOption("citations");
  await expect(page.getByTestId("result-card").first().getByRole("heading")).toHaveText(papers[2].title);

  const complete = page.getByTestId("result-card").filter({ hasText: papers[0].title });
  await complete.getByRole("button", { name: "Show details" }).click();
  await expect(complete).toContainText("10.1000/alpha");
  await expect(complete).toContainText("Alpha abstract about resilient retrieval.");
  await expect(complete.getByRole("link", { name: "Record" })).toHaveAttribute("href", papers[0].url);
  await expect(complete.getByRole("link", { name: "PDF" })).toHaveAttribute("href", papers[0].pdf_url);

  const sparse = page.getByTestId("result-card").filter({ hasText: papers[1].title });
  await sparse.getByRole("button", { name: "Show details" }).click();
  await expect(sparse).toContainText("Unknown authors");
  await expect(sparse).not.toContainText("undefined");
  await expect(sparse.getByRole("link", { name: "Record" })).toHaveCount(0);
  await expect(sparse.getByRole("link", { name: "PDF" })).toHaveCount(0);

  await expect(page.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
    "href",
    new RegExp(`/api/v1/runs/${runId}/export\\?format=csv$`),
  );
  await page.reload();
  await expect(page.getByTestId("selection-count")).toHaveText("0 selected");
});
