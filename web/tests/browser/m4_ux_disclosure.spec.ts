import { expect, test, type Page } from "@playwright/test";

const runId = "33333333-3333-4333-8333-333333333333";
const startedAt = new Date(Date.now() - 45_000).toISOString();

interface TimelineEvent {
  sequence: number;
  event_type: string;
  stage: string;
  payload: Record<string, unknown>;
}

function buildEvents(): TimelineEvent[] {
  return [
    { sequence: 1, event_type: "query.started", stage: "query.analyze", payload: { target_min: 5 } },
    { sequence: 2, event_type: "query.planned", stage: "query.plan", payload: { intent: "Map durable disclosure facts", question_type: "broad", current_query: "disclosure model", query_views: [{ view_id: "direct", purpose: "Direct" }] } },
    { sequence: 3, event_type: "query.progress", stage: "query.iterate", payload: { iteration: 1, decision: "accept", hit_count: 12, total: 31 } },
    { sequence: 4, event_type: "retrieval.started", stage: "retrieve.sources", payload: { lanes: ["relevance"], lane_concurrency: 2 } },
    { sequence: 5, event_type: "retrieval.progress", stage: "retrieve.sources", payload: { candidate_count: 18, completed_lanes: 1, total_lanes: 2 } },
    { sequence: 6, event_type: "retrieval.completed", stage: "retrieve.fuse", payload: { candidate_count: 24, total_candidates: 31, completed_lanes: 2, total_lanes: 2, fusion: "rrf", llm_gate_candidate_count: 24 } },
    { sequence: 7, event_type: "ranking.started", stage: "rank.results", payload: { candidate_count: 24, batch_count: 2, concurrency: 2 } },
    { sequence: 8, event_type: "ranking.batch_completed", stage: "rank.results", payload: { batch_count: 2, completed_batches: 1, scored_count: 12 } },
    { sequence: 9, event_type: "ranking.completed", stage: "rank.results", payload: { candidate_count: 24, scored_count: 24, warning_count: 0 } },
    { sequence: 10, event_type: "workflow.completed", stage: "workflow.completed", payload: { result_count: 7, warning_count: 0 } },
  ];
}

function sse(events: TimelineEvent[], after: number): string {
  return events
    .filter((event) => event.sequence > after)
    .map((event) => ({
      run_id: runId,
      sequence: event.sequence,
      event_type: event.event_type,
      stage: event.stage,
      occurred_at: startedAt,
      schema_version: 1,
      payload: event.payload,
    }))
    .map((event) => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`)
    .join("");
}

// The test gates the durable timeline: the app keeps cycling snapshot/replay,
// but new events are only released when the test advances `released`.
async function mockTimeline(page: Page, events: TimelineEvent[], finalStatus: string) {
  const gate = { released: 0, consumed: 0 };
  await page.route(`**/api/v1/runs/${runId}`, async (route) => {
    // The run only looks terminal once the client has replayed the full durable
    // stream, mirroring snapshot/SSE ordering in the real backend.
    const terminal = gate.consumed >= events.length;
    await route.fulfill({
      json: {
        id: runId,
        question: "Progressive disclosure timeline",
        source: "openalex",
        status: terminal ? finalStatus : "running",
        current_step: "rank.results",
        last_event_sequence: gate.consumed,
        result_count: terminal ? 7 : 0,
        warnings: [],
        created_at: startedAt,
        updated_at: startedAt,
        started_at: startedAt,
      },
    });
  });
  await page.route(`**/api/v1/runs/${runId}/events**`, async (route) => {
    const lastEventId = Number(route.request().headers()["last-event-id"] || 0);
    const target = Math.min(events.length, Math.max(gate.released, lastEventId));
    gate.consumed = Math.max(gate.consumed, target);
    await route.fulfill({ status: 200, headers: { "Content-Type": "text/event-stream" }, body: sse(events.slice(0, target), lastEventId) });
  });
  await page.route(`**/api/v1/runs/${runId}/audit**`, async (route) => {
    await route.fulfill({ json: { query_portfolio: [], loop_decisions: [], candidate_queue: {}, candidate_lifecycle: {}, recovery: {} } });
  });
  return gate;
}

test("idle search keeps four stages collapsed without placeholder progress", async ({ page }) => {
  await page.route("**/api/v1/sources", (route) => route.fulfill({ json: { sources: [] } }));
  await page.goto("/search");
  for (const key of ["query", "search", "ranking", "results"]) {
    await expect(page.getByTestId(`stage-${key}-toggle`)).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId(`stage-${key}`)).toHaveAttribute("data-state", "idle");
  }
  await expect(page.getByTestId("system-log-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("system-log-audit")).toHaveCount(0);
});

test("active stage expands with server-time elapsed; manual close survives later events", async ({ page }) => {
  const events = buildEvents();
  const gate = await mockTimeline(page, events, "completed");
  gate.released = 2;
  await page.goto(`/runs/${runId}`);

  // The current stage auto-expands and shows elapsed derived from occurred_at.
  await expect(page.getByTestId("stage-query-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("stage-query-elapsed")).toHaveText(/^\d+:\d\d$/);
  await expect(page.getByTestId("stage-search-toggle")).toHaveAttribute("aria-expanded", "false");

  // Manual close is a per-run choice and later stream events must not reset it.
  await page.getByTestId("stage-query-toggle").click();
  await expect(page.getByTestId("stage-query-toggle")).toHaveAttribute("aria-expanded", "false");
  gate.released = 5;
  await expect(page.getByTestId("stage-ranking-toggle")).toHaveAttribute("aria-expanded", "true", { timeout: 10_000 });
  await expect(page.getByTestId("stage-query-toggle")).toHaveAttribute("aria-expanded", "false");

  // Completion leaves the run on the workflow page with in-place entries.
  gate.released = events.length;
  await expect(page.getByTestId("run-status")).toHaveText("Completed", { timeout: 15_000 });
  await expect(page.getByTestId("stage-results")).toHaveAttribute("data-state", "complete");
  await expect(page.getByRole("link", { name: "View results" })).toHaveAttribute("href", `/runs/${runId}/results`);
  await expect(page.getByRole("link", { name: "View citation map" })).toHaveAttribute("href", `/runs/${runId}/citation-map`);
});

test("durable events advance through the four product stages with one active stage", async ({ page }) => {
  const events = buildEvents();
  const gate = await mockTimeline(page, events, "completed");
  gate.released = 2;
  await page.goto(`/runs/${runId}`);

  await expect(page.getByTestId("stage-query")).toHaveAttribute("data-state", "active");
  await expect(page.getByTestId("stage-search")).toHaveAttribute("data-state", "idle");
  await expect(page.getByTestId("stage-query-audit")).toContainText("Map durable disclosure facts");

  gate.released = 3;
  await expect(page.getByTestId("stage-query")).toHaveAttribute("data-state", "complete", { timeout: 10_000 });
  await expect(page.getByTestId("stage-search")).toHaveAttribute("data-state", "active");
  await expect(page.getByTestId("stage-search-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("stage-search-audit")).toContainText("Iteration 1");
  await expect(page.getByTestId("stage-search-audit")).toContainText("Accepted");
  await expect(page.getByTestId("stage-query-audit")).not.toContainText("Iteration 1");
  await expect(page.getByTestId("stage-search-toggle")).toContainText("1 iterations");
  await expect(page.getByTestId("stage-search-toggle")).toContainText("Source hits 12");
  await expect(page.getByTestId("stage-search-toggle")).toContainText("Accepted");

  gate.released = 5;
  await expect(page.getByTestId("stage-search")).toHaveAttribute("data-state", "complete", { timeout: 10_000 });
  await expect(page.getByTestId("stage-ranking")).toHaveAttribute("data-state", "active");
  await expect(page.getByTestId("stage-ranking-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("Multi-lane recall");
  await expect(page.getByTestId("stage-search-audit")).not.toContainText("Source retrieval");

  gate.released = 9;
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("LLM re-ranking", { timeout: 10_000 });
  gate.released = events.length;
  await expect(page.getByTestId("stage-results")).toHaveAttribute("data-state", "complete", { timeout: 15_000 });
});

test("a newly failed stage force-opens once and later respects a manual close", async ({ page }) => {
  const events = buildEvents().slice(0, 8);
  events.push({ sequence: 9, event_type: "ranking.failed", stage: "rank.results", payload: { code: "ranking_failed" } });
  const gate = await mockTimeline(page, events, "failed");
  gate.released = events.length;
  await page.goto(`/runs/${runId}`);

  await expect(page.getByTestId("stage-ranking-toggle")).toHaveAttribute("aria-expanded", "true", { timeout: 10_000 });
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("Ranking failed.");
  await expect(page.getByRole("link", { name: "Check configuration" })).toHaveAttribute("href", "/search");
  await expect(page.getByRole("button", { name: "View log" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Start a new search" })).toHaveAttribute("href", "/search");

  await page.getByTestId("stage-ranking-toggle").click();
  await expect(page.getByTestId("stage-ranking-toggle")).toHaveAttribute("aria-expanded", "false");
});

test("a cancelled run freezes stages and marks them cancelled", async ({ page }) => {
  const events = buildEvents().slice(0, 6);
  const gate = await mockTimeline(page, events, "cancelled");
  gate.released = events.length;
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status")).toHaveText("Cancelled", { timeout: 15_000 });
  await expect(page.getByText("Cancelled at the last confirmed progress; late responses were discarded.").first()).toBeAttached();
  await expect(page.getByTestId("stage-results")).toHaveAttribute("data-state", "idle");
});

test("the system log panel folds by default and manual state wins", async ({ page }) => {
  const events = buildEvents();
  const gate = await mockTimeline(page, events, "completed");
  gate.released = events.length;
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status")).toHaveText("Completed", { timeout: 15_000 });

  const toggle = page.getByTestId("system-log-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("system-log-audit")).toHaveCount(0);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("system-log-audit")).toContainText("workflow.completed");
  // Header facts stay visible in both states (§12).
  await expect(page.getByTestId("event-count")).toHaveText(String(events.length));

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("system-log-audit")).toHaveCount(0);
});

test("a real error auto-opens the log panel while the run is live", async ({ page }) => {
  const events = [
    ...buildEvents().slice(0, 8),
    { sequence: 9, event_type: "ranking.failed", stage: "rank.results", payload: { code: "ranking_failed" } },
    { sequence: 10, event_type: "workflow.completed", stage: "workflow.completed", payload: { result_count: 0, warning_count: 1 } },
  ];
  const gate = await mockTimeline(page, events, "failed");
  // Hold back the final event so the run stays live after the failure lands.
  gate.released = 9;
  await page.goto(`/runs/${runId}`);

  const toggle = page.getByTestId("system-log-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "true", { timeout: 10_000 });
  await expect(page.getByTestId("system-log-audit")).toContainText("ranking_failed");

  // Manual close wins, and the terminal transition must not reopen it (§12).
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  gate.released = events.length;
  await expect(page.getByTestId("run-status")).toHaveText("Failed", { timeout: 15_000 });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});
