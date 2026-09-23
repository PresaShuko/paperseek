import { expect, test } from "@playwright/test";

const runId = "33333333-3333-4333-8333-333333333333";
const question = "Cancel a running durable search";

function run(status: "running" | "cancelling" | "cancelled") {
  return {
    id: runId,
    question,
    source: "openalex",
    status,
    current_step: status,
    last_event_sequence: status === "cancelled" ? 4 : 1,
    result_count: 0,
    warnings: [],
    created_at: "2026-08-10T00:00:00Z",
    finished_at: status === "cancelled" ? "2026-08-10T00:01:00Z" : null,
  };
}

function sse(events: Array<Record<string, unknown>>): string {
  return events.map((event) =>
    `id: ${event.sequence}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`,
  ).join("");
}

test("Stop uses the cancel API and stale work cannot revive a cancelled run", async ({ page }) => {
  let snapshotCalls = 0;
  let streamCalls = 0;
  let cancelCalls = 0;
  let acknowledgeCancel!: () => void;
  let releaseCancelResponse!: () => void;
  let finishCancellation!: () => void;
  const cancelRequested = new Promise<void>((resolve) => { acknowledgeCancel = resolve; });
  const cancelResponseGate = new Promise<void>((resolve) => { releaseCancelResponse = resolve; });
  const terminalAllowed = new Promise<void>((resolve) => { finishCancellation = resolve; });

  const events = [
    [1, "retrieval.started", "retrieve.sources"],
    [2, "run.cancelling", "lifecycle"],
    [3, "workflow.completed", "workflow.completed"],
    [4, "run.cancelled", "lifecycle"],
  ].map(([sequence, event_type, stage]) => ({
    run_id: runId,
    sequence,
    event_type,
    stage,
    occurred_at: "2026-08-10T00:00:00Z",
    schema_version: 1,
    payload: {},
  }));

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === `/api/v1/runs/${runId}/cancel`) {
      cancelCalls += 1;
      expect(request.method()).toBe("POST");
      await cancelResponseGate;
      await route.fulfill({ status: 202, json: run("cancelling") });
      acknowledgeCancel();
    } else if (path === `/api/v1/runs/${runId}/events`) {
      streamCalls += 1;
      if (streamCalls === 1) {
        await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(events.slice(0, 1)) });
      } else {
        await terminalAllowed;
        await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(events.slice(1)) });
      }
    } else if (path === `/api/v1/runs/${runId}`) {
      snapshotCalls += 1;
      if (snapshotCalls === 1) {
        await route.fulfill({ json: run("running") });
      } else if (snapshotCalls === 2) {
        await cancelRequested;
        await new Promise((resolve) => setTimeout(resolve, 100));
        await route.fulfill({ json: run("running") });
      } else {
        await route.fulfill({ json: run("cancelled") });
      }
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });

  await page.goto(`/runs/${runId}`);
  await expect(page.locator('.stage-card[data-state="active"] .badge').first()).toHaveText("In progress");
  const stop = page.getByRole("button", { name: "Stop" });
  await expect(stop).toBeEnabled();
  await stop.click();
  // In-flight cancel: the same control shows the pending state and blocks repeats (§5.3).
  const stopping = page.getByRole("button", { name: "Stopping…" });
  await expect(stopping).toBeDisabled();
  expect(cancelCalls).toBe(1);

  releaseCancelResponse();
  await expect(page.locator('.stage-card[data-state="active"] .badge').first()).toHaveText("Cancelling");
  // The Stop control leaves the page once cancellation is in flight (§5.1);
  // it must not linger as a permanently disabled button.
  await expect(stop).toHaveCount(0);

  await page.waitForTimeout(200);
  await expect(page.locator('.stage-card[data-state="active"] .badge').first()).toHaveText("Cancelling");

  finishCancellation();
  await expect(page.getByTestId("stage-results").locator(".badge").first()).toHaveText("Cancelled");
  await expect(page.getByTestId("stage-results")).not.toHaveAttribute("data-state", "complete");
  await expect(stop).toHaveCount(0);
  expect(cancelCalls).toBe(1);
});
