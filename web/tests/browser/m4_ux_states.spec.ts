import { expect, test } from "@playwright/test";

const runId = "44444444-4444-4444-8444-444444444444";
const activeRun = {
  id: runId,
  question: "Active conflict run",
  source: "openalex",
  status: "running",
  current_step: "retrieve.sources",
  last_event_sequence: 1,
  result_count: 0,
  warnings: [],
  created_at: "2026-08-12T00:00:00Z",
  updated_at: "2026-08-12T00:00:00Z",
};

test("results load failure shows an actionable error, not an empty list", async ({ page }) => {
  let attempts = 0;
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: activeRun }));
  await page.route(`**/api/v1/runs/${runId}/results**`, async (route) => {
    attempts += 1;
    if (attempts === 1) await route.fulfill({ status: 500, json: { error: { code: "internal" } } });
    else await route.fulfill({ json: { results: [], next_cursor: null } });
  });
  await page.goto(`/runs/${runId}/results`);
  await expect(page.getByRole("alert")).toContainText("This could not be loaded.");
  await expect(page.getByText("No committed results are available.")).toHaveCount(0);
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("No committed results are available.")).toBeVisible();
  expect(attempts).toBe(2);
});

test("history distinguishes failure from empty and supports search and cursor paging", async ({ page }) => {
  const itemsPage1 = Array.from({ length: 3 }, (_, index) => ({
    ...activeRun,
    id: `44444444-4444-4444-8444-44444444444${index}`,
    question: `cardiology review ${index}`,
    status: "completed",
  }));
  const itemsPage2 = [{ ...activeRun, id: "55555555-5555-4555-8555-555555555555", question: "oncology survey", status: "failed" }];
  let allowSuccess = false;
  await page.route("**/api/v1/history**", async (route) => {
    if (!allowSuccess) {
      await route.fulfill({ status: 500, json: { error: { code: "internal" } } });
      return;
    }
    const url = new URL(route.request().url());
    if (url.searchParams.get("cursor") === "page-2") {
      await route.fulfill({ json: { items: itemsPage2, next_cursor: null } });
    } else {
      await route.fulfill({ json: { items: itemsPage1, next_cursor: "page-2" } });
    }
  });
  await page.goto("/history");
  await expect(page.getByRole("alert")).toContainText("This could not be loaded.");
  await expect(page.getByText("No search history yet.")).toHaveCount(0);

  allowSuccess = true;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("button", { name: /cardiology review 0/ })).toBeVisible();

  await page.getByLabel("Search history").fill("review 2");
  await expect(page.getByRole("button", { name: /cardiology review/ })).toHaveCount(1);
  await page.getByLabel("Search history").fill("");

  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByRole("button", { name: /oncology survey/ })).toBeVisible();
});

test("delete confirmation is a keyboard-operable dialog with focus return", async ({ page }) => {
  await page.route("**/api/v1/history**", (route) => route.fulfill({ json: { items: [activeRun], next_cursor: null } }));
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: activeRun }));
  await page.route(`**/api/v1/runs/${runId}/events`, (route) => route.fulfill({ contentType: "text/event-stream", body: "" }));
  await page.goto("/history");
  await page.getByRole("button", { name: /Active conflict run/ }).click();
  const deleteButton = page.getByRole("button", { name: "Delete run" });
  await deleteButton.click();
  const dialog = page.getByRole("dialog", { name: "Delete this search history" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(deleteButton).toBeFocused();
});

test("citation nodes are selectable from the keyboard", async ({ page }) => {
  const citationMap = {
    nodes: [
      { id: "n1", title: "Keyboard node alpha", roles: ["seed"], rank: 1, citations: 3 },
      { id: "n2", title: "Keyboard node beta", roles: ["forward"], citations: 1 },
    ],
    edges: [{ source: "n1", target: "n2" }],
  };
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: activeRun }));
  await page.route(`**/api/v1/runs/${runId}/citation-map`, (route) => route.fulfill({ json: citationMap }));
  await page.goto(`/runs/${runId}/citation-map`);
  const node = page.getByTestId("graph-node").first();
  await node.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("citation-detail")).toContainText("Keyboard node alpha");
});

test("an active-run conflict offers view and stop actions", async ({ page }) => {
  let cancelCalls = 0;
  await page.route("**/api/v1/sources", (route) => route.fulfill({
    json: { sources: [{ id: "openalex", label: "OpenAlex", default: true, status: "available", api_key: "not_required", capabilities: { filter: { mode: "none", label: "", options: [] }, citation_expansion: false }, credential: null }] },
  }));
  await page.route("**/api/v1/runs", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 409, json: { error: { code: "active_run_exists" } } });
    }
  });
  await page.route("**/api/v1/history**", (route) => route.fulfill({ json: { items: [activeRun], next_cursor: null } }));
  await page.route(`**/api/v1/runs/${runId}/cancel`, async (route) => {
    cancelCalls += 1;
    await route.fulfill({ status: 202, json: { ...activeRun, status: "cancelling" } });
  });
  await page.goto("/search");
  await page.getByLabel("Research Question").fill("Trigger the conflict path");
  await page.getByRole("button", { name: "Run Search" }).click();
  await expect(page.getByRole("alert")).toContainText("A search is already running");
  await expect(page.getByRole("link", { name: "View current run" })).toHaveAttribute("href", `/runs/${runId}`);
  await page.getByRole("button", { name: "Stop current run" }).click();
  expect(cancelCalls).toBe(1);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("Ctrl+Enter submits like the primary action", async ({ page }) => {
  let submissions = 0;
  await page.route("**/api/v1/sources", (route) => route.fulfill({
    json: { sources: [{ id: "openalex", label: "OpenAlex", default: true, status: "available", api_key: "not_required", capabilities: { filter: { mode: "none", label: "", options: [] }, citation_expansion: false }, credential: null }] },
  }));
  await page.route("**/api/v1/runs", async (route) => {
    if (route.request().method() === "POST") {
      submissions += 1;
      await route.fulfill({ status: 202, json: activeRun });
    }
  });
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: activeRun }));
  await page.route(`**/api/v1/runs/${runId}/events`, (route) => route.fulfill({ contentType: "text/event-stream", body: "" }));
  await page.goto("/search");
  await page.getByLabel("Research Question").fill("Keyboard submission path");
  await page.getByLabel("Research Question").press("Control+Enter");
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
  expect(submissions).toBe(1);
});
