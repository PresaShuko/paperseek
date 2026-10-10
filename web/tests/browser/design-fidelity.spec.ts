import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { createState, event, ids, withDocument, type MockState } from "./mock-backend";
import { open } from "./workspace-helpers";

const boards: Record<string, string[]> = JSON.parse(readFileSync(resolve(import.meta.dirname, "design-board-classes.json"), "utf-8"));
const report: Record<string, string[]> = {};

async function classes(page: Page, scope = ".inset") {
  await page.waitForTimeout(600);
  return page.evaluate((selector) => {
    const set = new Set<string>();
    for (const root of document.querySelectorAll(selector)) for (const el of [root, ...root.querySelectorAll("*")]) {
      const value = (el as HTMLElement).className;
      for (const name of (typeof value === "string" ? value : (value as SVGAnimatedString).baseVal).split(/\s+/)) if (name) set.add(name);
    }
    return [...set];
  }, scope);
}
function compare(name: string, found: string[]) {
  report[name] = boards[name].filter((item) => !found.includes(item));
}
function richState() {
  const state = createState();
  state.runs[ids.done].warnings = [];
  state.analyses = [];
  return state;
}
async function withReview(page: Page, state: MockState) {
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`, state);
  await page.getByRole("button", { name: "生成大纲" }).click();
  await page.waitForURL(/tab=outline/);
}

// Every class used by a design-canvas board (exported to design-board-classes.json)
// must appear when the matching page is driven into the board's state.
test("each page renders every element class of its design board", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  let state = richState();
  await open(page, "/search", state);
  await page.getByText("更多选项").click();
  compare("Main", await classes(page));

  const setup = richState(); setup.connections = []; setup.defaults.search_llm = "";
  await page.unrouteAll(); await open(page, "/search", setup);
  compare("MainSetup", await classes(page));

  state = richState();
  state.runs[ids.running] = { ...state.runs[ids.done], id: ids.running, status: "running", result_count: 0 };
  state.events[ids.running] = [event(ids.running, 1, "query.started"), event(ids.running, 2, "query.planned", { intent: "x" }),
    event(ids.running, 3, "query.progress", { iteration: 1, decision: "accept", hit_count: 3, total: 9 }),
    event(ids.running, 4, "retrieval.completed", { candidate_count: 24, total_candidates: 31 }),
    event(ids.running, 5, "citation.completed", { added_candidates: 8, candidate_count: 39 }),
    event(ids.running, 6, "ranking.batch_completed", { batch_count: 4, completed_batches: 2, scored_count: 12 })];
  await page.unrouteAll(); await open(page, `/runs/${ids.running}`, state);
  await page.getByTestId("stage-query-toggle").click();
  compare("Run", await classes(page));

  state = richState();
  state.runs[ids.queued] = { ...state.runs[ids.done], id: ids.queued, status: "queued", queue: { ahead: 2, running: 1 } };
  await page.unrouteAll(); await open(page, `/runs/${ids.queued}`, state);
  compare("RunQueued", await classes(page));

  await page.unrouteAll(); await open(page, `/runs/${ids.done}/results`, richState());
  await page.getByTestId("result-card").nth(0).getByRole("checkbox").check({ force: true });
  await page.getByTestId("result-card").nth(1).getByRole("checkbox").check({ force: true });
  compare("Results", await classes(page));

  await page.unrouteAll(); await open(page, "/history", richState());
  compare("History", await classes(page));

  state = richState();
  await page.unrouteAll(); await open(page, "/bibliometrics", state);
  compare("BiblioNew", await classes(page));
  await page.getByRole("radio", { name: /LLM screening/ }).click();
  await page.getByRole("button", { name: "开始分析" }).click();
  await page.waitForURL(/bibliometrics\/6666/);
  compare("Bibliometrics", await classes(page));
  await page.getByRole("tab", { name: "关键词主题" }).click();
  await page.getByRole("button", { name: "生成网络" }).click();
  compare("BiblioNetwork", await classes(page));
  await page.goto("/bibliometrics/history");
  compare("BiblioList", await classes(page));

  state = richState();
  await page.unrouteAll(); await open(page, "/reviews/new", state);
  compare("ReviewCreate", await classes(page));
  await page.getByRole("radio", { name: /LLM screening/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByRole("button", { name: "选择全部有摘要的" }).click();
  compare("ReviewPapers", await classes(page));
  await page.getByRole("button", { name: "下一步" }).click();
  compare("ReviewSetup", await classes(page));

  state = richState();
  await page.unrouteAll(); await withReview(page, state);
  await page.getByLabel("综述主线").fill("changed");
  compare("ReviewEditor", await classes(page));
  withDocument(state.reviews[0]);
  await page.goto(`/reviews/${ids.review}?tab=document`);
  await page.getByRole("button", { name: "证据 [1]" }).first().click();
  compare("ReviewDocument", await classes(page));
  await page.getByRole("tab", { name: "引用证据" }).click();
  await page.getByRole("radio", { name: "论文引用关系" }).check({ force: true });
  compare("CitationMap", await classes(page));
  await page.goto("/reviews");
  compare("Reviews", await classes(page));

  await page.unrouteAll(); await open(page, "/settings/models", richState());
  compare("Settings", await classes(page));
  await page.getByRole("button", { name: "添加连接" }).first().click();
  await page.getByLabel("API 密钥").fill("sk-test");
  await page.getByRole("button", { name: "测试连接" }).click();
  compare("SettingsConnection", await classes(page, "dialog[open]"));
  await page.keyboard.press("Escape");
  await page.goto("/settings/sources");
  compare("SettingsSources", await classes(page));

  expect(Object.keys(report)).toHaveLength(Object.keys(boards).length);
  expect(Object.fromEntries(Object.entries(report).filter(([, missing]) => missing.length))).toEqual({});
});
