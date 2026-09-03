import { expect, test, type Page } from "@playwright/test";

const runId = "66666666-6666-4666-8666-666666666666";
const startedAt = new Date(Date.now() - 30_000).toISOString();
const runningRun = {
  id: runId,
  question: "Responsive and accessible workbench",
  source: "openalex",
  status: "running",
  current_step: "retrieve.sources",
  last_event_sequence: 1,
  result_count: 0,
  warnings: [],
  created_at: startedAt,
  updated_at: startedAt,
  started_at: startedAt,
};
const sourcesPayload = {
  sources: [{
    id: "openalex", label: "OpenAlex", default: true, status: "available", api_key: "not_required",
    capabilities: { filter: { mode: "none", label: "", options: [] }, citation_expansion: true },
    credential: null,
  }],
};
const event = {
  run_id: runId, sequence: 1, event_type: "retrieval.started", stage: "retrieve.sources",
  occurred_at: startedAt, schema_version: 1, payload: { lanes: ["relevance"], total_lanes: 2, completed_lanes: 0 },
};

async function mockSearch(page: Page) {
  await page.route("**/api/v1/sources", (route) => route.fulfill({ json: sourcesPayload }));
}

async function mockRunningRun(page: Page) {
  await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: runningRun }));
  await page.route(`**/api/v1/runs/${runId}/events**`, (route) => route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    body: `id: 1\ndata: ${JSON.stringify(event)}\n\n`,
  }));
}

test("desktop search uses the dual-column workbench without horizontal overflow", async ({ page }) => {
  await mockSearch(page);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto("/search");
  await expect(page.getByLabel("Research Question")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const pane = await page.locator(".workbench-pane--config").boundingBox();
  expect(pane).not.toBeNull();
  expect(pane!.width).toBeGreaterThan(1366 * 0.3);
  expect(pane!.width).toBeLessThan(1366 * 0.45);
});

test("mobile keeps targets reachable, shows the slim stage bar and avoids overflow", async ({ page }) => {
  await mockSearch(page);
  await mockRunningRun(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/search");
  await expect(page.getByLabel("Research Question")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const primary = await page.getByRole("button", { name: "Run Search" }).boundingBox();
  expect(primary).not.toBeNull();
  expect(primary!.height).toBeGreaterThanOrEqual(44);

  await page.goto(`/runs/${runId}`);
  const stageBar = page.getByRole("button", { name: /Go to the current search stage/ });
  await expect(stageBar).toBeVisible();
  await expect(page.getByTestId("stage-ranking-toggle")).toHaveAttribute("aria-expanded", "true");
  await stageBar.click();
  await page.waitForTimeout(600);
  const top = await page.getByTestId("stage-ranking").evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.top < window.innerHeight && rect.bottom > 0;
  });
  expect(top).toBeTruthy();
});

test("320px running steps keep their labels horizontal and readable", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("paperseek.locale", "zh"));
  await mockRunningRun(page);
  const narrowEvents = [
    { ...event, sequence: 1, event_type: "retrieval.completed", payload: { candidate_count: 24, total_candidates: 31, completed_lanes: 2, total_lanes: 2 } },
    { ...event, sequence: 2, event_type: "ranking.started", stage: "rank.results", payload: { candidate_count: 24, batch_count: 2 } },
    { ...event, sequence: 3, event_type: "ranking.batch_completed", stage: "rank.results", payload: { completed_batches: 1, batch_count: 2, scored_count: 12 } },
  ];
  await page.route(`**/api/v1/runs/${runId}/events**`, (route) => route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    body: narrowEvents.map((item) => `id: ${item.sequence}\ndata: ${JSON.stringify(item)}\n\n`).join(""),
  }));
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto(`/runs/${runId}`);
  const boxes = await page.getByTestId("stage-ranking").locator(".step-name").evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  }));
  expect(boxes.length).toBeGreaterThanOrEqual(2);
  for (const box of boxes) {
    expect(box.width).toBeGreaterThan(150);
    expect(box.height).toBeLessThan(50);
  }
});

test("desktop hides the mobile stage bar", async ({ page }) => {
  await mockRunningRun(page);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status")).toHaveText("Running");
  await expect(page.getByRole("button", { name: /Go to the current search stage/ })).toBeHidden();
});

test("skip link is the first tab stop and disclosures expose aria-expanded", async ({ page }) => {
  await mockSearch(page);
  await page.goto("/search");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  const toggle = page.getByTestId("stage-query-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
});

test("reduced motion disables functional transitions", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockSearch(page);
  await page.goto("/search");
  const duration = await page.getByRole("button", { name: "Run Search" }).evaluate(
    (element) => getComputedStyle(element).transitionDuration,
  );
  expect(parseFloat(duration)).toBeLessThanOrEqual(0.011);
});
