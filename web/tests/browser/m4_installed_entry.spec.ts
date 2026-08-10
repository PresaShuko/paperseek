import { expect, test } from "@playwright/test";


test("installed Community entry serves Vue and records an explicit no-key failure", async ({ page }) => {
  test.skip(process.env.PAPERSEEK_REAL_ENTRY !== "1", "Requires a real local paperseek serve process.");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "PaperSeek" })).toBeVisible();
  await expect(page.getByLabel("Data Source")).toHaveValue("openalex");
  await expect(page.getByLabel("Data Source").locator("option")).toHaveCount(8);

  await page.getByRole("button", { name: "中文" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByLabel("研究问题")).toBeVisible();
  await page.getByRole("button", { name: "EN" }).click();

  const question = `M4 installed no-key boundary ${Date.now()}`;
  await page.getByLabel("Research Question").fill(question);
  await page.getByRole("button", { name: "Run Search" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Failed", { timeout: 15_000 });

  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("button", { name: new RegExp(question) })).toBeVisible();
});
