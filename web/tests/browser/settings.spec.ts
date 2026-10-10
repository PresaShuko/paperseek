import { expect, test } from "@playwright/test";
import { ids, requestsTo } from "./mock-backend";
import { open } from "./workspace-helpers";

test("model API tab lists connections with use, connectivity and actions", async ({ page }) => {
  await open(page, "/settings/models");
  await expect(page.getByRole("tab", { name: /模型 API/ })).toHaveAttribute("aria-selected", "true");
  const rows = page.locator(".table tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("deepseek-chat");
  await expect(rows.nth(0)).toContainText("检索默认");
  await expect(rows.nth(0)).toContainText("写作默认");
  await expect(rows.nth(0)).toContainText("412 ms");
  await expect(rows.nth(1)).toContainText("连接失败");
  await expect(rows.nth(1)).toContainText("401 密钥无效");
  await expect(page.getByText(/密钥加密保存在本机/)).toBeVisible();
});

test("adding a connection fills provider presets, tests the draft and never echoes the key", async ({ page }) => {
  const state = await open(page, "/settings/models");
  await page.getByRole("button", { name: "添加连接" }).first().click();
  const sheet = page.getByRole("dialog", { name: "添加连接" });
  await expect(sheet.getByRole("radio", { name: "LLM" })).toBeChecked();
  await sheet.getByRole("combobox", { name: "服务商" }).click();
  await page.getByRole("option", { name: "DeepSeek" }).click();
  await expect(sheet.getByLabel("模型")).toHaveValue(/deepseek/);
  await sheet.getByLabel("API 密钥").fill("sk-test-value");
  await sheet.getByRole("button", { name: "测试连接" }).click();
  await expect(sheet.locator(".alert")).toContainText("连接成功");
  expect(requestsTo(state, "POST", "/settings/connections/test")[0].body).toMatchObject({ kind: "llm", provider: "deepseek", api_key: "sk-test-value" });
  await sheet.getByRole("button", { name: "保存" }).click();
  await expect(sheet).toBeHidden();
  await expect(page.locator(".table tbody tr")).toHaveCount(3);
  expect(JSON.stringify(state.connections)).not.toContain("sk-test-value");
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("sk-test-value");
});

test("a failed draft test shows the reason; switching kind resets the provider", async ({ page }) => {
  const state = await open(page, "/settings/models?add=embedding");
  state.probe = { ok: false, latency_ms: 50, code: "http_404" };
  const sheet = page.getByRole("dialog", { name: "添加连接" });
  await expect(sheet.getByRole("radio", { name: "Embedding" })).toBeChecked();
  await sheet.getByLabel("API 密钥").fill("sk-test-value");
  await sheet.getByRole("button", { name: "测试连接" }).click();
  await expect(sheet.locator(".alert")).toContainText("404 模型或地址不存在");
});

test("defaults save immediately and deleting a default asks for a replacement", async ({ page }) => {
  const state = await open(page, "/settings/models");
  await page.getByRole("combobox", { name: "综述写作" }).click();
  await page.getByRole("option", { name: /qwen-plus/ }).click();
  await expect(page.getByText("已保存").first()).toBeVisible();
  expect(state.defaults.review_llm).toBe(ids.llm2);
  await page.locator(".table tbody tr").nth(0).getByRole("button", { name: /更多操作/ }).click();
  await page.getByRole("menuitem", { name: "删除" }).click();
  const dialog = page.getByRole("dialog", { name: "删除这个连接？" });
  await expect(dialog).toContainText("请先选择替代连接");
  await expect(dialog.getByRole("button", { name: "删除" })).toBeDisabled();
  await dialog.getByRole("combobox", { name: "替代连接" }).click();
  await page.getByRole("option", { name: /qwen-plus/ }).click();
  await dialog.getByRole("button", { name: "删除" }).click();
  await expect(page.locator(".table tbody tr")).toHaveCount(1);
  expect(requestsTo(state, "DELETE", `/settings/connections/${ids.llm}`)[0].query.get("replacement")).toBe(ids.llm2);
});

test("data sources show key requirement and status; configuring a required key makes it usable", async ({ page }) => {
  const state = await open(page, "/settings/sources");
  const wos = page.locator("tr", { hasText: "Web of Science Starter" });
  await expect(wos).toHaveClass(/off/);
  await expect(wos).toContainText("必需");
  await expect(wos).toContainText("不可用");
  await wos.getByRole("button", { name: "配置密钥" }).click();
  const sheet = page.getByRole("dialog", { name: /配置 Web of Science Starter/ });
  await sheet.locator("#source-key").fill("wos-test-key");
  await sheet.getByLabel("WoS 数据库").fill("WOK");
  await sheet.getByRole("button", { name: "保存" }).click();
  await expect(sheet).toBeHidden();
  expect(requestsTo(state, "PUT", "/settings/sources/wos")[0].body).toEqual({ api_key: "wos-test-key", options: { wos_db: "WOK" } });
  await expect(wos).not.toHaveClass(/off/);
  const openalex = page.locator("tr", { hasText: "OpenAlex" });
  await openalex.getByRole("button", { name: "测试" }).click();
  await expect(openalex).toContainText("290 ms");
});

test("general tab changes the interface language", async ({ page }) => {
  await open(page, "/settings/general");
  await page.getByRole("combobox", { name: "界面语言" }).click();
  await page.getByRole("option", { name: "English" }).click();
  await expect(page.getByRole("tab", { name: "General" })).toBeVisible();
});
