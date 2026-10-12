import { expect, test, type Page } from "@playwright/test";
import { ids } from "./mock-backend";
import { open } from "./workspace-helpers";

// Headless Chromium hides scrollbars by default, which would mask a scrollbar appearing on overflow.
const chrome = process.env.PAPERSEEK_BROWSER_EXECUTABLE ||
  (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined);
test.use({ launchOptions: { ...(chrome ? { executablePath: chrome } : {}), ignoreDefaultArgs: ["--hide-scrollbars"] } });

const overflows = (page: Page) => page.locator(".inset-main").evaluate((el) => el.scrollHeight > el.clientHeight);

/** Expanding a disclosure that makes the workspace start scrolling must not move content sideways. */
async function expectNoShift(page: Page, expand: () => Promise<void>) {
  const form = page.locator("main form").first();
  expect(await overflows(page)).toBe(false);
  const before = (await form.boundingBox())!.x;
  await expand();
  expect(await overflows(page)).toBe(true);
  expect((await form.boundingBox())!.x).toBe(before);
}

test("opening more options on a new search never shifts the page sideways", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 700 });
  await open(page, "/search");
  await page.getByText("更多选项").waitFor();
  await expectNoShift(page, () => page.getByText("更多选项").click());
});

test("opening more options in review setup never shifts the page sideways", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 840 });
  await open(page, `/reviews/new?source=${ids.done}&paper=uid-1&paper=uid-2`);
  await page.getByText("更多选项").waitFor();
  await expectNoShift(page, () => page.getByText("更多选项").click());
});
