import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Use an existing docs server for local inspection, or start the built site in CI.
export default defineConfig({
  ...base,
  testDir: "tests/docs",
  workers: 1,
  use: { ...base.use, baseURL: process.env.PAPERSEEK_BROWSER_BASE_URL || "http://127.0.0.1:4183" },
  webServer: process.env.PAPERSEEK_BROWSER_BASE_URL ? undefined : {
    command: "npm --prefix .. run docs:preview -- --host 127.0.0.1 --port 4183 --strictPort",
    url: "http://127.0.0.1:4183",
    reuseExistingServer: false,
  },
});
