import type { Page } from "@playwright/test";
import { createState, mockBackend, type MockState } from "./mock-backend";

/** Chinese UI against the in-memory API; returns the mutable mock state. */
export async function open(page: Page, path: string, state: MockState = createState(), language: "zh" | "en" = "zh") {
  await page.addInitScript((value) => {
    try { localStorage.setItem("paperseek.locale", value); } catch { /* storage blocked */ }
  }, language);
  await mockBackend(page, state);
  await page.goto(path);
  return state;
}

export async function noHorizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);
}
