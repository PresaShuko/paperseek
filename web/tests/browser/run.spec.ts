import { expect, test } from "@playwright/test";
import { createState, event, ids, requestsTo } from "./mock-backend";
import { open } from "./workspace-helpers";

test("a completed run shows four stages, metrics and the results entry", async ({ page }) => {
  await open(page, `/runs/${ids.done}`);
  await expect(page.getByRole("tab", { name: "运行过程" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: /检索结果/ })).toContainText("6");
  for (const key of ["query", "search", "ranking", "results"]) await expect(page.getByTestId(`stage-${key}`)).toHaveAttribute("data-state", "complete");
  await expect(page.getByTestId("stage-query")).toContainText("Compare LLM screening with humans");
  await page.getByTestId("stage-ranking-toggle").click();
  await expect(page.getByTestId("stage-ranking-audit")).toContainText("融合后候选");
  await page.getByTestId("stage-results").getByRole("link", { name: "查看结果" }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${ids.done}/results`));
});

test("a running run expands the active stage, disables results and confirms before stopping", async ({ page }) => {
  const state = createState();
  state.runs[ids.running] = { ...state.runs[ids.done], id: ids.running, status: "running", result_count: 0, last_event_sequence: 4 };
  state.events[ids.running] = [
    event(ids.running, 1, "query.started"),
    event(ids.running, 2, "query.planned", { intent: "Intent" }),
    event(ids.running, 3, "query.progress", { iteration: 1, decision: "accept", hit_count: 3, total: 9 }),
    event(ids.running, 4, "retrieval.progress", { candidate_count: 18, completed_lanes: 1, total_lanes: 2 }),
  ];
  await open(page, `/runs/${ids.running}`, state);
  await expect(page.getByTestId("stage-ranking")).toHaveAttribute("open", "");
  await expect(page.getByTestId("stage-ranking")).toContainText("进行中");
  await expect(page.getByRole("tab", { name: "检索结果" })).toHaveAttribute("aria-disabled", "true");
  await page.getByRole("button", { name: "停止" }).click();
  const dialog = page.getByRole("dialog", { name: "停止这次检索？" });
  await expect(dialog).toContainText("已完成的阶段会保留");
  await dialog.getByRole("button", { name: "停止" }).click();
  await expect.poll(() => requestsTo(state, "POST", `/runs/${ids.running}/cancel`).length).toBe(1);
});

test("a queued run shows queue position and cancels after confirmation", async ({ page }) => {
  const state = createState();
  state.runs[ids.queued] = { ...state.runs[ids.done], id: ids.queued, status: "queued", result_count: 0, queue: { ahead: 2, running: 1 } };
  await open(page, `/runs/${ids.queued}`, state);
  const card = page.getByTestId("queue-status");
  await expect(card).toContainText("正在等待执行");
  await expect(card).toContainText("2");
  await card.getByRole("button", { name: "取消排队" }).click();
  await page.getByRole("dialog", { name: "取消排队？" }).getByRole("button", { name: "取消排队" }).click();
  await expect.poll(() => requestsTo(state, "POST", `/runs/${ids.queued}/cancel`).length).toBe(1);
});

test("a failed run explains the error and run settings are read-only with rerun", async ({ page }) => {
  await open(page, `/runs/${ids.failed}`);
  await expect(page.getByTestId("run-primary-summary")).toContainText("检索失败");
  await page.getByRole("button", { name: "检索设置" }).click();
  const dialog = page.getByRole("dialog", { name: "检索设置" });
  await expect(dialog).toContainText("Failed search");
  await expect(dialog).toContainText("deepseek-chat");
  await dialog.getByTestId("rerun-edit").click();
  await expect(page).toHaveURL(/\/search$/);
  await expect(page.getByLabel("研究问题")).toHaveValue("Failed search");
});
