import { expect, test } from "@playwright/test";
import { createState, ids, requestsTo } from "./mock-backend";
import { open } from "./workspace-helpers";

test("search history is a table with status badges, server search and row actions", async ({ page }) => {
  const state = await open(page, "/history");
  const rows = page.locator(".table tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(page.locator("tr", { hasText: "Failed search" })).toContainText("失败");
  await page.getByRole("searchbox", { name: "搜索研究问题…" }).fill("Tiny");
  await expect(rows).toHaveCount(1);
  await expect(page.getByTestId("history-matched")).toHaveText("共 1 条");
  await rows.first().getByRole("button", { name: /更多操作/ }).click();
  await page.getByRole("menuitem", { name: "重命名" }).click();
  await page.getByLabel("显示标题").fill("Renamed");
  await page.getByRole("button", { name: "保存" }).click();
  expect(requestsTo(state, "PATCH", `/history/${ids.small}`)[0].body).toEqual({ title: "Renamed" });
});

test("clearing finished history confirms first", async ({ page }) => {
  const state = await open(page, "/history");
  await page.getByRole("button", { name: "清空已结束历史" }).click();
  const dialog = page.getByRole("dialog", { name: "清空已结束的检索？" });
  await dialog.getByRole("button", { name: "清空已结束历史" }).click();
  await expect(dialog).toBeHidden();
  expect(state.deleted.sort()).toEqual([ids.done, ids.small, ids.failed].sort());
});

test("new analysis only offers completed searches and opens the overview", async ({ page }) => {
  const state = createState();
  state.runs[ids.running] = { ...state.runs[ids.done], id: ids.running, question: "Running search", status: "running" };
  await open(page, "/bibliometrics", state);
  await expect(page.getByRole("radio", { name: /Running search/ })).toHaveAttribute("aria-disabled", "true");
  await expect(page.getByRole("button", { name: "开始分析" })).toBeDisabled();
  await page.getByRole("radio", { name: /LLM screening/ }).click();
  await page.getByRole("button", { name: "开始分析" }).click();
  await expect(page).toHaveURL(new RegExp(`/bibliometrics/${ids.analysis}`));
  await expect(page.locator(".stat-value").first()).toHaveText("642");
  await expect(page.getByText("原生被引次数合计")).toBeVisible();
  await expect(page.locator(".card-title", { hasText: "数据源" })).toHaveCount(0);
  await page.getByRole("tab", { name: "关键词主题" }).click();
  await expect(page).toHaveURL(/view=keywords/);
  await page.getByRole("button", { name: "生成网络" }).click();
  await expect(page.getByRole("button", { name: "systematic review, 148" })).toBeVisible();
  expect(requestsTo(state, "POST", `/bibliometrics/${ids.analysis}/network`)[0].body).toMatchObject({ kind: "keywords", min_occurrences: 3, min_weight: 2 });
  await page.getByRole("tab", { name: "数据质量" }).click();
  await expect(page.locator(".table")).toContainText("640 / 642");
});

test("analysis and review lists are tables with a create action", async ({ page }) => {
  await open(page, "/bibliometrics/history");
  await expect(page.getByText("还没有计量分析")).toBeVisible();
  await page.getByRole("link", { name: "新建分析" }).last().click();
  await expect(page).toHaveURL(/\/bibliometrics$/);
  await page.goto("/reviews");
  await expect(page.getByText("还没有综述")).toBeVisible();
});
