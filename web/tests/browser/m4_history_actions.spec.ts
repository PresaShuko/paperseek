import { expect, test } from "@playwright/test";

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
