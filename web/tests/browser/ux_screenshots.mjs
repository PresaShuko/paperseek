import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const base = process.env.PAPERSEEK_BROWSER_BASE_URL || "http://127.0.0.1:4173";
const out = process.env.SHOT_DIR || "../../.cutover-tmp/m4-ux-shots";
await mkdir(out, { recursive: true });

const sources = {
  sources: [
    { id: "openalex", label: "OpenAlex", default: true, status: "available", api_key: "optional",
      capabilities: { filter: { mode: "native", label: "Fields of study", options: [{ id: "27", label: "Medicine", domain: "Health Sciences" }, { id: "17", label: "Computer Science", domain: "Physical Sciences" }] }, citation_expansion: true },
      credential: { requirement: "optional", input_label: "OpenAlex API Key", guidance_label: "Get an OpenAlex key", guidance_url: "https://example.com" } },
    { id: "arxiv", label: "arXiv", default: false, status: "available", api_key: "not_required",
      capabilities: { filter: { mode: "none", label: "", options: [] }, citation_expansion: false }, credential: null },
  ],
};

const runId = "11111111-1111-4111-8111-111111111111";
const startedAt = new Date(Date.now() - 95_000).toISOString();
const runningRun = {
  id: runId, question: "大语言模型在医疗领域的应用有哪些？其在诊断、治疗建议和患者管理方面的效果如何？", source: "openalex", status: "running",
  current_step: "rank.results", last_event_sequence: 6, result_count: 0, warnings: [],
  created_at: startedAt, updated_at: startedAt, started_at: startedAt,
};
const completedRun = { ...runningRun, status: "completed", result_count: 2 };
const warningRun = { ...completedRun, status: "completed_with_warnings", warnings: ["retrieval_lane_failed:impact", "abstract_enrichment_failed:10.1000/example"] };
const failedRun = { ...runningRun, status: "failed", current_step: "ranking.failed", warnings: ["retrieval_partial"], error_code: "ranking_failed" };
const cancelledRun = { ...runningRun, status: "cancelled", current_step: "cancelled" };
const rawEvents = [
  [1, "query.started", "query.analyze", { target_min: 5, target_max: 50 }],
  [2, "query.planned", "query.plan", { intent: "识别大语言模型在医疗场景中的应用与效果证据", question_type: "broad_landscape", current_query: "large language model healthcare diagnosis", query_views: [{ view_id: "direct", purpose: "Direct terminology" }] }],
  [3, "retrieval.started", "retrieve.sources", { lanes: ["relevance", "recent"], lane_concurrency: 2 }],
  [4, "retrieval.completed", "retrieve.fuse", { candidate_count: 24, total_candidates: 31, completed_lanes: 2, total_lanes: 2, lane_concurrency: 2, fusion: "rrf", llm_gate_candidate_count: 24 }],
  [5, "ranking.started", "rank.results", { candidate_count: 24, llm_gate_candidate_count: 24, batch_count: 2, concurrency: 2 }],
  [6, "ranking.batch_completed", "rank.results", { batch_count: 2, completed_batches: 1, scored_count: 12 }],
];
const rawCompletedEvents = [
  ...rawEvents.slice(0, 5),
  [6, "ranking.completed", "rank.results", { candidate_count: 24, scored_count: 24, warning_count: 0 }],
  [7, "enrichment.completed", "enrich.results", { request_count: 2, enriched_count: 2, warning_count: 0, current: 2, total: 2, concurrency: 2 }],
  [8, "workflow.completed", "workflow.completed", { result_count: 2, warning_count: 0 }],
];
const toEvents = (raw) => raw.map(([sequence, event_type, stage, payload]) => ({
  run_id: runId, sequence, event_type, stage, occurred_at: startedAt, schema_version: 1, payload,
}));
const events = toEvents(rawEvents);
const completedEvents = toEvents(rawCompletedEvents);
const failedEvents = toEvents([
  ...rawEvents.slice(0, 5),
  [6, "ranking.failed", "rank.results", { code: "ranking_failed", failed_candidates: 24 }],
]);
const cancelledEvents = toEvents(rawEvents.slice(0, 4));
const papers = [
  { rank: 1, title: "Large language models for clinical diagnosis: a systematic review", authors: ["Jane Doe", "John Smith"], year: 2026, venue: "Nature Digital Medicine", provider: "openalex", score: 9.2, citation_count: 128, doi: "10.1234/example.1", abstract: "We review evidence for large language models in clinical workflows.", reasoning: "Direct match for diagnosis and patient management outcomes.", url: "https://example.com/paper1", pdf_url: "https://example.com/paper1.pdf" },
  { rank: 2, title: "Evaluation of LLM treatment recommendations in primary care", authors: ["Alice Lee"], year: 2025, venue: "JMIR", provider: "openalex", score: 8.1, citation_count: 42, doi: "10.1234/example.2", abstract: "A prospective evaluation of treatment recommendation quality.", url: "https://example.com/paper2" },
];
const citationMap = {
  nodes: [
    { id: "n1", title: papers[0].title, roles: ["seed"], rank: 1, citations: 128, year: 2026, source: "openalex", score: 9.2, reasoning: "Seed paper." },
    { id: "n2", title: "Prior work on clinical NLP", roles: ["backward"], citations: 300, year: 2023, source: "openalex" },
    { id: "n3", title: "Follow-up validation study", roles: ["forward"], citations: 12, year: 2026, source: "openalex" },
  ],
  edges: [{ source: "n2", target: "n1" }, { source: "n1", target: "n3" }],
};

const browser = await chromium.launch({
  executablePath: process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined,
});
const page = await browser.newPage();
await page.route("**/api/v1/sources", (route) => route.fulfill({ json: sources }));
let currentResults = {
  results: papers, next_cursor: null,
  total_count: papers.length, matched_count: papers.length, scored_count: papers.length,
  high_score_count: papers.filter((paper) => paper.score >= 5).length, max_score: 9.2,
};
await page.route(`**/api/v1/runs/${runId}/results**`, (route) => route.fulfill({ json: currentResults }));
await page.route(`**/api/v1/runs/${runId}/citation-map`, (route) => route.fulfill({ json: citationMap }));
await page.route(`**/api/v1/runs/${runId}/audit**`, (route) => route.fulfill({ json: { query_portfolio: [], loop_decisions: [], candidate_queue: {}, candidate_lifecycle: {}, recovery: {} } }));
await page.route("**/api/v1/history**", (route) => route.fulfill({ json: { items: [completedRun], next_cursor: null } }));

let currentRun = runningRun;
let currentEvents = events;
await page.route(`**/api/v1/runs/${runId}`, (route) => route.fulfill({ json: currentRun }));
await page.route(`**/api/v1/runs/${runId}/events**`, (route) => route.fulfill({
  status: 200, headers: { "Content-Type": "text/event-stream" },
  body: currentEvents.map((event) => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`).join(""),
}));

async function shot(name) {
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 1) throw new Error(`${name} horizontal overflow: ${overflow}px`);
  console.log("shot", name, "overflow", overflow);
}

// Terminal, degraded, connection and technical-detail states at the release desktop viewport.
await page.setViewportSize({ width: 1366, height: 900 });
for (const [name, snapshot, timeline] of [
  ["warning", warningRun, completedEvents],
  ["failed", failedRun, failedEvents],
  ["cancelled", cancelledRun, cancelledEvents],
]) {
  currentRun = snapshot; currentEvents = timeline;
  await page.goto(`${base}/runs/${runId}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  await shot(`desktop-run-${name}`);
}
currentRun = runningRun; currentEvents = events;
await page.goto(`${base}/runs/${runId}`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1200);
await shot("desktop-run-reconnecting");

const viewports = [
  ["desktop", 1366, 900],
  ["desktop-lg", 1440, 900],
  ["desktop-md", 1024, 768],
  ["tablet", 768, 1024],
  ["mobile-414", 414, 896],
  ["mobile", 390, 844],
  ["mobile-375", 375, 812],
  ["mobile-sm", 320, 568],
];

for (const [name, width, height] of viewports) {
  await page.setViewportSize({ width, height });
  currentRun = runningRun; currentEvents = events;
  await page.goto(`${base}/search`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);
  await shot(`${name}-search`);
  await page.goto(`${base}/runs/${runId}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1400);
  await shot(`${name}-run-running`);
  currentRun = completedRun; currentEvents = completedEvents;
  await page.goto(`${base}/runs/${runId}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1400);
  await shot(`${name}-run-complete`);
  await page.goto(`${base}/runs/${runId}/results`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);
  await shot(`${name}-results`);
  await page.goto(`${base}/runs/${runId}/citation-map`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);
  await shot(`${name}-citation-map`);
  await page.goto(`${base}/history`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);
  await shot(`${name}-history`);
}

// 200% browser zoom on the desktop search and run pages (§16.2)
await page.setViewportSize({ width: 1366, height: 900 });
currentRun = runningRun; currentEvents = events;
await page.goto(`${base}/search`, { waitUntil: "domcontentloaded" });
await page.evaluate(() => { document.body.style.zoom = "200%"; });
await page.waitForTimeout(600);
await shot("zoom200-search");
const overflowZoom = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
console.log("zoom200 horizontal overflow px:", overflowZoom);

// Chinese run view for bilingual copy review
await page.evaluate(() => { document.body.style.zoom = "100%"; });
await page.goto(`${base}/runs/${runId}`, { waitUntil: "domcontentloaded" });
await page.getByRole("button", { name: "中文" }).click();
await page.waitForTimeout(1200);
await shot("desktop-run-running-zh");
await page.goto(`${base}/search`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(800);
await shot("desktop-search-zh");
currentRun = completedRun; currentEvents = completedEvents;
await page.goto(`${base}/history`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(800);
await shot("desktop-history-zh");

// Scoring-failure results state: banner + unscored cards (§8.1/§8.2)
await page.evaluate(() => { document.body.style.zoom = "100%"; });
await page.setViewportSize({ width: 1366, height: 900 });
currentRun = { ...completedRun, warnings: ["ranking_failed_local_order_retained"] };
currentResults = {
  results: papers.map((paper) => ({ ...paper, score: null })), next_cursor: null,
  total_count: papers.length, matched_count: papers.length, scored_count: 0, high_score_count: 0, max_score: null,
};
await page.goto(`${base}/runs/${runId}/results`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(900);
await shot("desktop-results-scoring-failed");

await browser.close();
console.log("screenshots written to", out);
