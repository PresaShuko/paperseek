import { expect, test } from "@playwright/test";
import { createState, ids, requestsTo, withDocument } from "./mock-backend";
import { open } from "./workspace-helpers";

test("new review goes search → papers → setup and starts the outline with a saved connection", async ({ page }) => {
  const state = await open(page, "/reviews/new");
  await expect(page.getByRole("radio", { name: /Tiny search/ })).toHaveAttribute("aria-disabled", "true");
  await expect(page.getByRole("radio", { name: /Tiny search/ })).toContainText("结果不足 2 篇");
  await page.getByRole("radio", { name: /LLM screening/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.locator("[aria-current=step]")).toContainText("选择文献");
  const noAbstract = page.locator(".paper-pick.off");
  await expect(noAbstract).toContainText("无摘要");
  await expect(noAbstract.getByRole("checkbox")).toBeDisabled();
  await expect(page.getByRole("button", { name: "下一步" })).toBeDisabled();
  await page.getByRole("button", { name: "选择全部有摘要的" }).click();
  await expect(page.getByText("已选 3 / 100 篇")).toBeVisible();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByLabel("综述主题")).toHaveValue("LLM screening for systematic reviews");
  await page.getByRole("radiogroup", { name: "篇幅" }).getByRole("radio", { name: /自定义/ }).check({ force: true });
  await page.getByRole("spinbutton", { name: "章节数" }).fill("5");
  await expect(page.getByRole("combobox", { name: "每章段落数" })).toBeHidden();
  await page.getByText("更多选项").click();
  await expect(page.getByRole("combobox", { name: "每章段落数" })).toContainText("自动");
  await page.getByRole("combobox", { name: "每章段落数" }).click();
  await expect(page.getByRole("option", { name: /自动/ })).toContainText("随篇幅 5–7 段");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "生成大纲" }).click();
  await expect(page).toHaveURL(new RegExp(`/reviews/${ids.review}\\?tab=outline`));
  const body = requestsTo(state, "POST", "/reviews")[0].body;
  expect(body).toMatchObject({ section_count: 5, length: "detailed", paper_uids: ["uid-1", "uid-2", "uid-3"] });
  expect(body).not.toHaveProperty("paragraph_count");
  expect(body).not.toHaveProperty("paragraph_length");
  expect(requestsTo(state, "POST", `/reviews/${ids.review}/jobs`)[0].body).toMatchObject({ action: "prepare_outline", connection_id: ids.llm });
});

test("selection from results lands on the setup step", async ({ page }) => {
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`);
  await expect(page.locator("[aria-current=step]")).toContainText("写作设置");
  await expect(page.getByText("2 篇文献")).toBeVisible();
});

test("paragraph count and length offer presets and custom values in the output language's unit", async ({ page }) => {
  const state = createState();
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`, state);
  await page.getByText("更多选项").click();
  await page.getByRole("combobox", { name: "每章段落数" }).click();
  await page.getByRole("option", { name: /充实/ }).click();
  await page.getByRole("combobox", { name: "每段长度" }).click();
  await expect(page.getByRole("option", { name: /充实/ })).toContainText("约 450 字");
  await page.getByRole("option", { name: /自定义/ }).click();
  await page.getByRole("spinbutton", { name: "每段长度" }).fill("320");
  await expect(page.locator("summary")).toContainText("2 项已修改");
  await page.getByRole("button", { name: "生成大纲" }).click();
  await expect(page).toHaveURL(/tab=outline/);
  expect(requestsTo(state, "POST", "/reviews")[0].body).toMatchObject({ paragraph_count: 5, paragraph_length: 320 });
});

test("paragraph length switches to words for English output", async ({ page }) => {
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`);
  await page.getByRole("combobox", { name: "输出语言" }).click();
  await page.getByRole("option", { name: "English" }).click();
  await page.getByText("更多选项").click();
  await page.getByRole("combobox", { name: "每段长度" }).click();
  await expect(page.getByRole("option", { name: /充实/ })).toContainText("约 250 词");
  await page.getByRole("option", { name: /自定义/ }).click();
  await expect(page.getByRole("spinbutton", { name: "每段长度" })).toHaveValue("150");
});

test("outline edits show the unsaved bar and save through the outline endpoint", async ({ page }) => {
  const state = createState();
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`, state);
  await page.getByRole("button", { name: "生成大纲" }).click();
  await expect(page.getByLabel("综述主线")).toHaveValue("Compare recall and workload.");
  await page.getByRole("button", { name: /Reproducibility/ }).click();
  await page.getByLabel("章节标题").fill("Bias and reporting");
  const bar = page.getByRole("region", { name: "大纲有未保存的修改" });
  await expect(bar).toBeVisible();
  await bar.getByRole("button", { name: "保存" }).click();
  await expect(bar).toBeHidden();
  expect(requestsTo(state, "PUT", `/reviews/${ids.review}/outline`)[0].body.outline.sections[1].title).toBe("Bias and reporting");
});

test("draft shows the table of contents and an evidence popover; evidence tab switches views", async ({ page }) => {
  const state = createState();
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`, state);
  await page.getByRole("button", { name: "生成大纲" }).click();
  await expect(page).toHaveURL(/tab=outline/);
  withDocument(state.reviews[0]);
  await page.goto(`/reviews/${ids.review}?tab=document`);
  await expect(page.getByRole("navigation", { name: "大纲" })).toContainText("Screening performance");
  await page.getByRole("button", { name: "证据 [1]" }).first().click();
  const popover = page.getByRole("dialog", { name: "证据 [1]" });
  await expect(popover).toContainText("Quote from Paper 1 on screening");
  await page.keyboard.press("Escape");
  await expect(popover).toBeHidden();
  await page.getByRole("tab", { name: "引用证据" }).click();
  await page.getByRole("radio", { name: "论文引用关系" }).check({ force: true });
  await expect(page.getByTestId("citation-graph")).toBeVisible();
});

test("citation map selects nodes from the graph and the text list", async ({ page }) => {
  await open(page, `/runs/${ids.done}/citation-map`);
  await expect(page.getByRole("list", { name: "引用图例" })).toContainText("种子");
  await expect(page.getByTestId("citation-detail")).toContainText("Seed paper");
  await page.getByTestId("citation-text-list").locator("summary").click();
  await page.getByTestId("citation-text-list").getByRole("button", { name: /Result paper/ }).click();
  await expect(page.getByTestId("citation-detail")).toContainText("Result paper");
  await expect(page.getByTestId("citation-detail-score")).toHaveText("7/10");
});

test("a failed writing task offers a retry that resubmits the same action", async ({ page }) => {
  const state = createState();
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`, state);
  await page.getByRole("button", { name: "生成大纲" }).click();
  await expect(page).toHaveURL(/tab=outline/);
  const review = state.reviews[0];
  review.latest_job = { ...review.latest_job, status: "failed", error_code: "review_model_output_invalid" };
  review.latest_request = { action: "write", section_id: "", instruction: "" };
  review.generation_failure = { task: "section_sources", reason: "Paragraph 5: synthesize within 900 characters." };
  await page.reload();
  const alert = page.getByRole("alert").filter({ hasText: "返回内容经自动修复后仍未通过格式校验" });
  await expect(alert).toContainText("段落引用");
  await alert.getByRole("button", { name: "重试" }).click();
  await expect.poll(() => requestsTo(state, "POST", `/reviews/${ids.review}/jobs`).at(-1)?.body).toMatchObject({ action: "write", connection_id: ids.llm });
});
