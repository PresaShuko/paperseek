import { expect, test } from "@playwright/test";

const runId = "11111111-1111-4111-8111-111111111111";
const secondRunId = "22222222-2222-4222-8222-222222222222";

function run(id: string, question: string, status = "completed") {
  return {
    id,
    question,
    source: "openalex",
    status,
    current_step: status === "completed" ? "workflow.completed" : "retrieve.sources",
    last_event_sequence: status === "completed" ? 8 : 2,
    result_count: 1,
    warnings: [],
    created_at: "2026-08-10T00:00:00Z",
    finished_at: status === "completed" ? "2026-08-10T00:01:00Z" : null,
  };
}

const firstQuestion = "Recover the durable first run";
const secondQuestion = "Keep the second route authoritative";
const completedRun = run(runId, firstQuestion);
const secondRun = run(secondRunId, secondQuestion);
const events = [
  [1, "query.started", "query.analyze", { target_min: 5, target_max: 50 }],
  [2, "query.planned", "query.plan", {
    intent: "Recover durable research facts",
    question_type: "broad_landscape",
    current_query: "durable run recovery",
    query_views: [{ view_id: "direct", purpose: "Direct recovery terminology" }],
  }],
  [3, "retrieval.started", "retrieve.sources", { lanes: ["relevance", "recent"], lane_concurrency: 2 }],
  [4, "retrieval.completed", "retrieve.fuse", { candidate_count: 24, total_candidates: 31, completed_lanes: 2, total_lanes: 2, lane_concurrency: 2, fusion: "rrf", llm_gate_candidate_count: 24 }],
  [5, "ranking.started", "rank.results", { candidate_count: 24, llm_gate_candidate_count: 24, batch_count: 2, concurrency: 2 }],
  [6, "ranking.completed", "rank.results", { scored_count: 24, warning_count: 0 }],
  [7, "enrichment.completed", "enrich.results", { request_count: 1, enriched_count: 1, warning_count: 0, current: 1, total: 1, concurrency: 2 }],
  [8, "workflow.completed", "workflow.completed", { result_count: 1, warning_count: 0 }],
].map(([sequence, event_type, stage, payload]) => ({
  run_id: runId,
  sequence,
  event_type,
  stage,
  occurred_at: "2026-08-10T00:00:00Z",
  schema_version: 1,
  payload,
}));

const audit = {
  query_portfolio: [
    {
      view_id: "direct",
      status: "completed",
      query: "durable recovery audit",
      total: 11,
      hit_count: 6,
      added_unique: 4,
    },
  ],
  loop_decisions: [
    {
      iteration: 1,
      query: "durable run recovery",
      total: 24,
      action: "accept",
      message: "Accepted the durable recovery query.",
    },
  ],
  candidate_queue: {
    keys: ["paper-1", "paper-2"],
    origin_counts: { retrieval: 2 },
    duplicate_count: 1,
    ledger_summary: { total_candidates: 2, serialized_candidates: 2, omitted_candidates: 0 },
  },
  candidate_lifecycle: {
    ledger_candidates: 2,
    selected_for_llm: 2,
    final_output: 1,
    ledger_retained: 2,
  },
  recovery: { query: 1, retrieval: 0, citation: 0, ranking: 0, enrichment: 0, total: 1 },
};

function sse(items: typeof events): string {
  return items.map((event) =>
    `id: ${event.sequence}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`,
  ).join("");
}

test("run URL refresh replays, de-duplicates and reconnects with Last-Event-ID", async ({ page }) => {
  let streamCalls = 0;
  const cursors: string[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === `/api/v1/runs/${runId}/events`) {
      cursors.push(request.headers()["last-event-id"] || "");
      streamCalls += 1;
      if (streamCalls === 1) {
        await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(events.slice(0, 2)) });
      } else if (streamCalls === 2) {
        await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse([events[1], ...events.slice(2)]) });
      } else {
        await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(events) });
      }
    } else if (path === `/api/v1/runs/${runId}`) {
      await route.fulfill({ json: streamCalls >= 2 ? completedRun : run(runId, firstQuestion, "running") });
    } else if (path === `/api/v1/runs/${runId}/audit`) {
      await route.fulfill({ json: audit });
    } else if (path === `/api/v1/runs/${runId}/results`) {
      await route.fulfill({ json: { results: [{ rank: 1, title: "Recovered result", metadata_status: "complete" }], next_cursor: null } });
    } else if (path === `/api/v1/runs/${runId}/citation-map`) {
      await route.fulfill({ json: { nodes: [{ id: "p1", title: "Recovered node" }], edges: [] } });
    } else if (path === "/api/v1/history") {
      await route.fulfill({ json: { items: [completedRun], next_cursor: null } });
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });

  await page.goto(`/runs/${runId}`);
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
  await expect(page.getByTestId("run-status")).toHaveText("Completed");
  // Diagnostic facts live in the log panel header, visible without expanding (§12).
  await expect(page.getByTestId("system-log-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("last-event-sequence")).toHaveText("8");
  await expect(page.getByTestId("event-count")).toHaveText("8");
  expect(cursors.slice(0, 2)).toEqual(["0", "2"]);

  await page.getByTestId("stage-query-toggle").click();
  await expect(page.getByTestId("stage-query-audit")).toContainText("Recover durable research facts");
  await expect(page.getByTestId("stage-query-audit")).toContainText("durable run recovery");
  await expect(page.getByTestId("stage-search-audit")).not.toContainText("Source retrieval");
  await page.getByTestId("stage-ranking-toggle").click();
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("Loaded candidates 24");
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("Fused candidates 31");
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("LLM re-ranking");
  await page.getByTestId("stage-results-toggle").click();
  await expect(page.getByTestId("stage-results-audit")).toContainText("Results");
  // Retrieval/ranking/enrichment event rows live in stage 03's folded detail section.
  await page.getByTestId("stage-ranking-process-toggle").click();
  await expect(page.getByTestId("retrieval-progress-audit")).toContainText("Loaded candidates 24");
  await expect(page.getByTestId("retrieval-progress-audit")).toContainText("Fused candidates 31");
  await expect(page.getByTestId("ranking-progress-audit")).toContainText("Ranking batches 0 / 2");
  await expect(page.getByTestId("ranking-progress-audit")).toContainText("Sent to LLM 24");
  await expect(page.getByTestId("enrichment-progress-audit")).toContainText("Abstracts completed 1 / 1");
  await page.getByTestId("system-log-toggle").click();
  await expect(page.getByTestId("system-log-audit")).toContainText("000008");
  await expect(page.getByTestId("system-log-audit")).toContainText("workflow.completed");
  await expect(page.getByTestId("system-log-export")).toHaveAttribute("href", `/api/v1/runs/${runId}/logs`);
  await page.getByRole("button", { name: "中文" }).click();
  await expect(page.getByTestId("system-log-toggle")).toContainText("系统日志");
  await expect(page.getByTestId("stage-search-portfolio-toggle")).toHaveText("查询组合");
  await expect(page.getByTestId("stage-search-audit-toggle")).toHaveText("技术审计");
  await expect(page.getByTestId("stage-ranking-audit-toggle")).toHaveText("恢复与候选审计");
  await page.getByRole("button", { name: "EN" }).click();
  await expect(page.getByTestId("stage-query-toggle")).toHaveAttribute("aria-expanded", "true");

  await page.getByTestId("stage-search-toggle").click();
  await page.getByTestId("stage-search-portfolio-toggle").click();
  await expect(page.getByTestId("query-portfolio-audit")).toContainText("durable recovery audit");
  await expect(page.getByTestId("query-portfolio-audit")).toContainText("New candidates 4");
  await page.getByTestId("stage-search-audit-toggle").click();
  await expect(page.getByTestId("technical-audit")).toContainText("Accepted the durable recovery query.");
  await expect(page.getByTestId("technical-audit")).toContainText("duplicate_count");
  await page.getByTestId("stage-ranking-audit-toggle").click();
  await expect(page.getByTestId("candidate-recovery-audit")).toContainText("ledger_candidates");
  await expect(page.getByTestId("candidate-recovery-audit")).toContainText('"total": 1');

  await page.reload();
  await expect(page.getByTestId("run-status")).toHaveText("Completed");
  await expect(page.getByTestId("event-count")).toHaveText("8");
  await page.getByTestId("stage-query-toggle").click();
  await expect(page.getByTestId("stage-query-audit")).toContainText("Recover durable research facts");
  await page.getByTestId("stage-search-toggle").click();
  await page.getByTestId("stage-search-portfolio-toggle").click();
  await expect(page.getByTestId("query-portfolio-audit")).toContainText("durable recovery audit");

  await page.goto(`/runs/${runId}/results`);
  await expect(page.getByRole("heading", { name: firstQuestion })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recovered result" })).toBeVisible();
  await expect(page.getByTestId("result-score")).toHaveText("Not scored");
  await page.goto(`/runs/${runId}/citation-map`);
  await expect(page.getByRole("heading", { name: firstQuestion })).toBeVisible();
  await expect(page.getByTestId("citation-detail")).toContainText("Recovered node");

  await page.goto("/history");
  const flow = page.getByTestId(`history-flow-${runId}`);
  const results = page.getByTestId(`history-results-${runId}`);
  const citationMap = page.getByTestId(`history-citation-map-${runId}`);
  await expect(flow).toHaveAttribute("href", `/runs/${runId}`);
  await expect(results).toHaveAttribute("href", `/runs/${runId}/results`);
  await expect(citationMap).toHaveAttribute("href", `/runs/${runId}/citation-map`);
  await flow.click();
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
  await page.getByRole("navigation", { name: "Workspace section" }).getByRole("link", { name: "Results" }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}/results$`));
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}/results$`));
});

test("a failed stage automatically exposes its durable structured fact", async ({ page }) => {
  const failedRun = run(runId, "Expose the durable failure", "failed");
  failedRun.current_step = "ranking.failed";
  failedRun.last_event_sequence = 2;
  const failedEvents = [
    { ...events[0], run_id: runId },
    {
      run_id: runId,
      sequence: 2,
      event_type: "ranking.failed",
      stage: "ranking",
      occurred_at: "2026-08-10T00:00:02Z",
      schema_version: 1,
      payload: { code: "ranking_failed", failed_candidates: 24 },
    },
  ];
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/v1/runs/${runId}`) await route.fulfill({ json: failedRun });
    else if (path === `/api/v1/runs/${runId}/events`) {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(failedEvents as typeof events) });
    } else await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status")).toHaveText("Failed");
  await expect(page.getByTestId("stage-ranking-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("stage-query-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("Ranking failed.");
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("Affected candidates 24");
  // A terminal failed run keeps the log folded; the user opens it (§12).
  await expect(page.getByTestId("system-log-toggle")).toHaveAttribute("aria-expanded", "false");
  await page.getByTestId("system-log-toggle").click();
  await expect(page.getByTestId("system-log-audit")).toContainText("ranking_failed");
});

test("running audit is restored from durable decision, portfolio and recovery events", async ({ page }) => {
  const running = run(runId, "Restore in-progress technical audit", "running");
  running.last_event_sequence = 5;
  const liveEvents = [
    { ...events[0], run_id: runId },
    { ...events[1], run_id: runId },
    {
      run_id: runId,
      sequence: 3,
      event_type: "query.progress",
      stage: "query",
      occurred_at: "2026-08-10T00:00:03Z",
      schema_version: 1,
      payload: { iteration: 1, query: "durable run recovery", total: 24, decision: "accept", message: "Accepted live query", reason: "within target" },
    },
    {
      run_id: runId,
      sequence: 4,
      event_type: "query.portfolio_recorded",
      stage: "query",
      occurred_at: "2026-08-10T00:00:04Z",
      schema_version: 1,
      payload: { view_id: "live-view", query: "live portfolio query", status: "completed", hit_count: 3, added_unique: 2 },
    },
    {
      run_id: runId,
      sequence: 5,
      event_type: "workflow.recovery",
      stage: "workflow",
      occurred_at: "2026-08-10T00:00:05Z",
      schema_version: 1,
      payload: { query: 1, retrieval: 1, citation: 0, ranking: 0, enrichment: 0 },
    },
  ];
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/v1/runs/${runId}`) await route.fulfill({ json: running });
    else if (path === `/api/v1/runs/${runId}/events`) {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(liveEvents as typeof events) });
    } else await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto(`/runs/${runId}`);
  // Stage 02 is the live stage, so it is already expanded (§5.2).
  await expect(page.getByTestId("stage-search-toggle")).toHaveAttribute("aria-expanded", "true");
  await page.getByTestId("stage-search-portfolio-toggle").click();
  await expect(page.getByTestId("query-portfolio-audit")).toContainText("live portfolio query");
  await page.getByTestId("stage-search-audit-toggle").click();
  await expect(page.getByTestId("technical-audit")).toContainText("Accepted live query");
  await page.getByTestId("stage-ranking-toggle").click();
  await page.getByTestId("stage-ranking-audit-toggle").click();
  await expect(page.getByTestId("candidate-recovery-audit")).toContainText('"total": 2');
});

test("a late response from a previous run cannot replace the current route", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/history") {
      await route.fulfill({ json: { items: [completedRun, secondRun], next_cursor: null } });
      return;
    }
    if (path.includes(runId)) await new Promise((resolve) => setTimeout(resolve, 300));
    const selected = path.includes(secondRunId) ? secondRun : completedRun;
    if (path.endsWith("/results")) {
      await route.fulfill({ json: { results: [{ rank: 1, title: `${selected.question} result` }], next_cursor: null } });
    } else if (path === `/api/v1/runs/${selected.id}`) {
      await route.fulfill({ json: selected });
    } else {
      await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    }
  });

  await page.goto("/history");
  await page.getByTestId(`history-results-${runId}`).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}/results$`));
  await page.goBack();
  await page.getByTestId(`history-results-${secondRunId}`).click();
  await expect(page.getByRole("heading", { name: secondQuestion, exact: true })).toBeVisible();
  await page.waitForTimeout(400);
  await expect(page.getByRole("heading", { name: secondQuestion, exact: true })).toBeVisible();
  await expect(page.getByText(`${secondQuestion} result`)).toBeVisible();
  await expect(page.getByText(`${firstQuestion} result`)).toHaveCount(0);
});
