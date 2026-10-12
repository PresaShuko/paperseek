import { defineConfig } from "@playwright/test";

const chrome = process.env.PAPERSEEK_BROWSER_EXECUTABLE ||
  (process.platform === "win32"
    ? "C:/Program Files/Google/Chrome/Application/chrome.exe"
    : undefined);

export default defineConfig({
  testDir: "tests/browser",
  fullyParallel: false,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: process.env.PAPERSEEK_BROWSER_BASE_URL || "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    launchOptions: chrome ? { executablePath: chrome } : {},
    trace: "retain-on-failure",
  },
});
