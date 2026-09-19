import { expect, test, type Page } from "@playwright/test";

const runId = "88888888-8888-4888-8888-888888888888";
const run = {
  id: runId,
  question: "history behavior",
  source: "openalex",
  status: "failed",
  current_step: "rank.results",
  last_event_sequence: 2,
  result_count: 0,
  error_code: "ranking_failed",
  warnings: ["retrieval_partial"],
  created_at: "2026-08-12T00:00:00Z",
  finished_at: "2026-08-12T00:01:00Z",
};
const events = [
  { run_id: runId, sequence: 1, event_type: "retrieval.degraded", stage: "retrieve.sources", occurred_at: run.created_at, schema_version: 1, payload: { warning: "retrieval_partial" } },
  { run_id: runId, sequence: 2, event_type: "ranking.failed", stage: "rank.results", occurred_at: run.finished_at, schema_version: 1, payload: { code: "ranking_failed" } },
];

function sse(): string {
  return events.map((event) => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`).join("");
}

async function prepareClear(page: Page, options: { failPage?: boolean; failDelete?: boolean; pauseDelete?: Promise<void> } = {}) {
  const saved = [run, { ...run, id: "second-run", question: "second saved run", status: "cancelled" },
    { ...run, id: "active-run", question: "active search", status: "running" }];
  const deleted: string[] = [];
  const requests: string[] = [];
  await page.addInitScript(() => localStorage.setItem("paperseek.locale", "en"));
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/history") {
      if (url.searchParams.has("cursor") && options.failPage) return route.fulfill({ status: 503, json: { error: { code: "storage_unavailable" } } });
      const items = saved.filter(item => !deleted.includes(item.id));
      return route.fulfill({ json: url.searchParams.has("cursor")
        ? { items: items.filter(item => item.id === "second-run"), next_cursor: null }
        : { items: items.filter(item => item.id !== "second-run"), next_cursor: items.some(item => item.id === "second-run") ? "older" : null } });
    }
    if (request.method() === "DELETE") {
      const id = url.pathname.split("/").pop()!;
      requests.push(id);
      if (options.pauseDelete) await options.pauseDelete;
      if (id === "second-run" && options.failDelete) return route.fulfill({ status: 503, json: { error: { code: "storage_unavailable" } } });
      deleted.push(id);
      return route.fulfill({ status: 202, json: { run_id: id, status: "cleanup_pending" } });
    }
    return route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });
  await page.goto("/history");
  return { deleted, requests };
}

test("clear history confirms once, includes unloaded pages and keeps active runs regardless of the filter", async ({ page }) => {
  const { requests, deleted } = await prepareClear(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const clear = page.getByRole("button", { name: "Clear finished history", exact: true });
  await clear.click();
  const dialog = page.getByRole("dialog", { name: "Clear all finished search history" });
  await expect(dialog).toContainText("including pages and searches not currently shown");
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await page.screenshot({ path: test.info().outputPath("clear-confirmation-mobile.png") });
  await page.keyboard.press("Escape");
  await expect(clear).toBeFocused();
  expect(requests).toEqual([]);
  await page.getByRole("searchbox").fill("active search");
  await clear.click();
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(deleted).toEqual([runId, "second-run"]);
  expect(requests).not.toContain("active-run");
  await expect(page.getByRole("button", { name: /active search/ })).toBeVisible();
  await expect(clear).toBeDisabled();
  await expect(page.getByRole("button", { name: "Refresh history", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "中文", exact: true }).click();
  await expect(page.getByRole("button", { name: "清空已结束历史", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("history listing failure does not partially clear a page", async ({ page }) => {
  const { requests } = await prepareClear(page, { failPage: true });
  await page.getByRole("button", { name: "Clear finished history", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("could not be completed");
  expect(requests).toEqual([]);
  await expect(page.getByRole("button", { name: /history behavior/ })).toBeVisible();
});

test("a partial clear stays visible as a failure and retry does not restore deleted history", async ({ page }) => {
  const options = { failDelete: true };
  const { deleted, requests } = await prepareClear(page, options);
  await page.getByRole("button", { name: "中文", exact: true }).click();
  await page.getByRole("button", { name: "清空已结束历史", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "删除", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("已删除的历史不会恢复");
  await page.screenshot({ path: test.info().outputPath("clear-partial-failure-zh.png") });
  expect(deleted).toEqual([runId]);
  await expect(page.getByRole("button", { name: /history behavior/ })).toHaveCount(0);
  options.failDelete = false;
  await dialog.getByRole("button", { name: "删除", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(requests).toEqual([runId, "second-run", "second-run"]);
});

test("leaving history stops the remaining clear requests even if an accepted delete completes late", async ({ page }) => {
  await page.goto("/search");
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const { requests, deleted } = await prepareClear(page, { pauseDelete: pending });
  await page.getByRole("button", { name: "Clear finished history", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  await page.goBack();
  release();
  await expect.poll(() => deleted.length).toBe(1);
  await expect(page).toHaveURL(/\/search$/);
  expect(requests).toEqual([runId]);
});

test("history refreshes, shows durable detail and deletes one confirmed terminal run", async ({ page }) => {
  let historyReads = 0;
  let deleteCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/history") {
      historyReads += 1;
      await route.fulfill({ json: { items: deleteCalls ? [] : [run], next_cursor: null } });
    } else if (path === `/api/v1/runs/${runId}`) {
      await route.fulfill({ json: run });
    } else if (path === `/api/v1/runs/${runId}/events`) {
      await route.fulfill({ contentType: "text/event-stream", body: sse() });
    } else if (path === `/api/v1/history/${runId}` && request.method() === "DELETE") {
      deleteCalls += 1;
      await route.fulfill({ status: 202, json: { run_id: runId, status: "deleted" } });
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });

  await page.goto("/history");
  await page.getByRole("button", { name: "Refresh history" }).click();
  expect(historyReads).toBe(2);
  await page.getByRole("button", { name: new RegExp(run.question) }).click();
  const detail = page.getByTestId("history-detail");
  await expect(page.getByTestId("history-primary-detail")).toContainText("Retrieval completed with partial coverage.");
  await expect(page.getByTestId("history-primary-detail")).toContainText("Ranking failed.");
  await expect(page.getByTestId("history-primary-detail")).not.toContainText("ranking_failed");
  await page.getByTestId("history-technical-audit-toggle").click();
  await expect(page.getByTestId("history-technical-audit")).toContainText("000002 ranking.failed");

  await expect(detail.getByRole("link", { name: "Workflow" })).toHaveAttribute("href", `/runs/${runId}`);
  await expect(detail.getByRole("link", { name: "Results" })).toHaveAttribute("href", `/runs/${runId}/results`);
  await expect(detail.getByRole("link", { name: "Citation Map" })).toHaveAttribute("href", `/runs/${runId}/citation-map`);
  await expect(detail.getByRole("link", { name: "Export CSV" })).toHaveAttribute("href", new RegExp(`/api/v1/runs/${runId}/export\\?format=csv$`));
  await expect(detail.getByRole("link", { name: "Export JSON" })).toHaveAttribute("href", new RegExp(`/api/v1/runs/${runId}/export\\?format=json$`));

  await detail.getByRole("button", { name: "Delete run" }).click();
  await page.getByRole("dialog", { name: "Delete this search history" })
    .getByRole("button", { name: "Cancel" }).click();
  expect(deleteCalls).toBe(0);
  await detail.getByRole("button", { name: "Delete run" }).click();
  await page.getByRole("dialog", { name: "Delete this search history" })
    .getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText(run.question)).toHaveCount(0);
  expect(deleteCalls).toBe(1);
});
