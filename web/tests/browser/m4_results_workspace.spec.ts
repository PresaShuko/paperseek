import { expect, test, type Page } from "@playwright/test";

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
    uid: "uid-alpha",
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
    uid: "uid-beta",
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
    uid: "uid-gamma",
    rank: 3,
    title: "Gamma cited record",
    authors_text: "Grace Researcher",
    publish_year: 2025,
    score: 7.4,
    citations: "42",
    doi: "10.1000/gamma",
    url: "https://example.test/gamma",
    provider: "crossref",
    metadata_status: "degraded",
  },
  {
    uid: "uid-delta",
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

type Params = Record<string, string | null>;

// Server-side stand-in: applies query/min_score/metadata/sort exactly like the contract.
function queryResults(params: Params) {
  let list = [...papers];
  const needle = (params.query || "").trim().toLowerCase();
  if (needle) {
    list = list.filter((paper) =>
      [paper.title, ...(paper.authors || []), paper.authors_text, paper.abstract, paper.doi, paper.venue]
        .filter(Boolean).join(" ").toLowerCase().includes(needle));
  }
  const minScore = params.min_score;
  if (minScore) list = list.filter((paper) => paper.score >= Number(minScore));
  if (params.metadata === "abstract") list = list.filter((paper) => Boolean(paper.abstract));
  if (params.metadata === "doi") list = list.filter((paper) => Boolean(paper.doi));
  if (params.metadata === "pdf") list = list.filter((paper) => Boolean(paper.pdf_url));
  const sort = params.sort || "rank";
  if (sort === "score") list = list.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  if (sort === "citations") list = list.sort((a, b) => Number(b.citations) - Number(a.citations));
  if (sort === "year") list = list.sort((a, b) => b.publish_year - a.publish_year);
  return list;
}

function pagePayload(list: typeof papers, cursor: string | null, filtered: boolean, total = papers.length) {
  // The default view pages by two; filtered queries return the full match set.
  const paged = !filtered && !cursor && list.length > 2;
  const page = cursor === "page-2" ? list.slice(2) : paged ? list.slice(0, 2) : list;
  const scored = list.filter((paper) => paper.score !== null && paper.score !== undefined);
  return {
    results: page,
    next_cursor: paged ? "page-2" : null,
    total_count: total,
    matched_count: list.length,
    scored_count: scored.length,
    high_score_count: scored.filter((paper) => paper.score >= 5).length,
    max_score: scored.length ? Math.max(...scored.map((paper) => paper.score)) : null,
  };
}

async function mockResults(page: Page, requests: Params[], exportBodies: Array<Record<string, unknown>>) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === `/api/v1/runs/${runId}`) {
      await route.fulfill({ json: run });
    } else if (url.pathname === `/api/v1/runs/${runId}/results`) {
      const params: Params = {
        cursor: url.searchParams.get("cursor"),
        query: url.searchParams.get("query"),
        min_score: url.searchParams.get("min_score"),
        metadata: url.searchParams.get("metadata"),
        sort: url.searchParams.get("sort"),
      };
      requests.push(params);
      const filtered = Boolean(params.query || params.min_score || params.metadata || (params.sort && params.sort !== "rank"));
      await route.fulfill({ json: pagePayload(queryResults(params), params.cursor, filtered) });
    } else if (url.pathname === `/api/v1/runs/${runId}/export-selected` && request.method() === "POST") {
      const body = request.postDataJSON();
      exportBodies.push(body);
      const uids: string[] = body.uids || [];
      await route.fulfill({
        headers: { "Content-Disposition": `attachment; filename="selected.${body.format}"` },
        contentType: body.format === "csv" ? "text/csv" : "application/json",
        body: body.format === "csv" ? `uid\n${uids.join("\n")}` : JSON.stringify({ uids }),
      });
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });
}

test("results workspace pages, filters, sorts, selects and exports through the server contract", async ({ page }) => {
  const requests: Params[] = [];
  const exportBodies: Array<Record<string, unknown>> = [];
  await mockResults(page, requests, exportBodies);

  await page.goto(`/runs/${runId}/results`);
  await expect(page.getByRole("heading", { name: papers[0].title })).toBeVisible();
  await expect(page.getByText(papers[2].title)).toHaveCount(0);
  await expect(page.getByTestId("results-summary")).toContainText("4 results · 4 scored");
  await expect(page.getByTestId("results-summary")).toContainText("4 with score ≥ 5 · top score 9.2");
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByRole("heading", { name: papers[2].title })).toBeVisible();
  expect(requests.map((entry) => entry.cursor)).toEqual([null, "page-2"]);

  // Keyword search is debounced, resets the cursor and goes to the server.
  await page.getByLabel("Search results").fill("Gamma");
  await expect(page.getByTestId("result-card")).toHaveCount(1);
  expect(requests.at(-1)).toMatchObject({ query: "Gamma", cursor: null });
  await expect(page.getByTestId("results-summary")).toContainText("1 match the filters");
  await page.getByRole("button", { name: "Select all shown" }).click();
  await expect(page.getByTestId("selection-count")).toHaveText("1 selected");

  // Selected export posts the stable uids and downloads the returned file.
  const download = page.waitForEvent("download");
  await page.getByTestId("export-selected-csv").click();
  expect((await download).suggestedFilename()).toBe("selected.csv");
  expect(exportBodies).toEqual([{ format: "csv", uids: ["uid-gamma"] }]);
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(page.getByTestId("selection-count")).toHaveText("0 selected");
  await expect(page.getByTestId("export-selected-csv")).toBeDisabled();

  await page.getByLabel("Search results").fill("");
  await expect(page.getByTestId("result-card")).toHaveCount(2);
  await page.getByLabel("Availability").selectOption("pdf");
  await expect(page.getByText(papers[1].title)).toHaveCount(0);
  expect(requests.at(-1)).toMatchObject({ metadata: "pdf", cursor: null });
  await page.getByLabel("Availability").selectOption("all");
  await page.getByLabel("Minimum score").selectOption("8");
  await expect(page.getByText(papers[2].title)).toHaveCount(0);
  await expect(page.getByTestId("result-card")).toHaveCount(3);
  expect(requests.at(-1)).toMatchObject({ min_score: "8", cursor: null });
  await page.getByLabel("Minimum score").selectOption("all");
  await page.getByLabel("Sort results").selectOption("citations");
  await expect(page.getByTestId("result-card")).toHaveCount(4);
  expect(requests.at(-1)).toMatchObject({ sort: "citations", cursor: null });
  await expect(page.getByTestId("result-card").first().getByRole("heading")).toHaveText(papers[2].title);

  const complete = page.getByTestId("result-card").filter({ hasText: papers[0].title });
  await complete.getByRole("button", { name: "Bibliographic details" }).click();
  await expect(complete).toContainText("10.1000/alpha");
  await expect(complete).toContainText("Alpha abstract about resilient retrieval.");
  await expect(complete.getByRole("link", { name: "Record" }).first()).toHaveAttribute("href", papers[0].url);
  await expect(complete.getByRole("link", { name: "PDF" })).toHaveAttribute("href", papers[0].pdf_url);
  await expect(complete.getByTestId("result-score")).toContainText("8.1/10");
  // The metadata status badge is gone (§8.2).
  await expect(complete.getByTestId("metadata-status")).toHaveCount(0);

  const sparse = page.getByTestId("result-card").filter({ hasText: papers[1].title });
  await expect(sparse).toContainText("Unknown authors");
  await expect(sparse).toContainText("No abstract provided.");
  await expect(sparse).not.toContainText("undefined");
  await expect(sparse.getByRole("link", { name: "Record" })).toHaveCount(0);
  await expect(sparse.getByRole("link", { name: "PDF" })).toHaveCount(0);

  const degraded = page.getByTestId("result-card").filter({ hasText: papers[2].title });
  await expect(degraded).toContainText("The abstract could not be retrieved.");

  await expect(page.getByRole("link", { name: "Export all CSV" })).toHaveAttribute(
    "href",
    new RegExp(`/api/v1/runs/${runId}/export\\?format=csv$`),
  );
  await expect(page.getByRole("link", { name: "Back to search progress" })).toHaveAttribute("href", `/runs/${runId}`);
  await page.reload();
  await expect(page.getByTestId("selection-count")).toHaveText("0 selected");
});

test("legal zero scores, unscored papers and the degraded banner use server facts", async ({ page }) => {
  const scoredRun = { ...run, warnings: ["ranking_partial_failure_local_order_retained", "citation_expansion_partial"] };
  const mixed = [
    { uid: "uid-zero", rank: 1, title: "Zero score record", authors: ["A"], score: 0, citations: "1", url: "https://example.test/zero" },
    { uid: "uid-none", rank: 2, title: "Unscored record", authors: ["B"], score: null, relevance_score: null, citations: "0" },
    { uid: "uid-seven", rank: 3, title: "Seven score record", authors: ["C"], score: 7, citations: "3" },
  ];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === `/api/v1/runs/${runId}`) await route.fulfill({ json: scoredRun });
    else if (url.pathname === `/api/v1/runs/${runId}/results`) {
      await route.fulfill({ json: {
        results: mixed,
        next_cursor: null,
        total_count: 3,
        matched_count: 3,
        scored_count: 2,
        high_score_count: 1,
        max_score: 7,
      } });
    } else await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto(`/runs/${runId}/results`);
  await expect(page.getByTestId("ranking-banner")).toHaveText("Some papers were not scored; unscored items are kept.");
  await expect(page.getByTestId("results-summary")).toContainText("3 results · 2 scored");
  await expect(page.getByTestId("results-summary")).toContainText("1 with score ≥ 5 · top score 7");
  const zero = page.getByTestId("result-card").filter({ hasText: "Zero score record" });
  await expect(zero.getByTestId("result-score")).toContainText("0/10");
  const unscored = page.getByTestId("result-card").filter({ hasText: "Unscored record" });
  await expect(unscored.getByTestId("result-score")).toHaveText("Not scored");
  await expect(unscored).not.toContainText("0/10");

  // A full ranking failure replaces the partial wording (§8.1).
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({
    json: { ...run, warnings: ["ranking_failed_local_order_retained"] },
  }));
  await page.reload();
  await expect(page.getByTestId("ranking-banner")).toHaveText("Model scoring did not complete this run; results are shown in local pre-ranked order.");
  await page.getByRole("button", { name: "中文" }).click();
  await expect(page.getByTestId("ranking-banner")).toHaveText("本次模型评分未完成，以下按本地预排序展示。");
  await expect(page.getByTestId("results-summary")).toContainText("共 3 篇 · 成功评分 2 篇");
});

test("a filter change keeps the selection and reports how many fall outside", async ({ page }) => {
  const requests: Params[] = [];
  await mockResults(page, requests, []);
  await page.goto(`/runs/${runId}/results`);
  await page.getByTestId("result-card").first().locator('input[type="checkbox"]').check();
  await expect(page.getByTestId("selection-count")).toHaveText("1 selected");
  await page.getByLabel("Search results").fill("Gamma");
  await expect(page.getByTestId("result-card")).toHaveCount(1);
  await expect(page.getByTestId("selection-count")).toHaveText("1 selected");
  await expect(page.getByTestId("selection-out-of-filter")).toHaveText("1 selected are outside the current filter");
});

test("a failed page load keeps loaded results and retries in place", async ({ page }) => {
  let pageTwoAttempts = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === `/api/v1/runs/${runId}`) await route.fulfill({ json: run });
    else if (url.pathname === `/api/v1/runs/${runId}/results`) {
      if (url.searchParams.get("cursor") === "page-2") {
        pageTwoAttempts += 1;
        if (pageTwoAttempts === 1) {
          await route.fulfill({ status: 500, json: { error: { code: "internal" } } });
          return;
        }
      }
      await route.fulfill({ json: pagePayload(queryResults({ cursor: url.searchParams.get("cursor") }), url.searchParams.get("cursor"), false) });
    } else await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto(`/runs/${runId}/results`);
  await expect(page.getByRole("heading", { name: papers[0].title })).toBeVisible();
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByRole("alert")).toContainText("This could not be loaded.");
  await expect(page.getByRole("heading", { name: papers[0].title })).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("heading", { name: papers[2].title })).toBeVisible();
  expect(pageTwoAttempts).toBe(2);
});
