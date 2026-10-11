// Render the finished hero painting (public/hero-painting.html) as the static
// poster shown before it starts and when it cannot run.
//   node docs/.vitepress/hero-poster.mjs
// Uses the web package's Playwright; set PAPERSEEK_BROWSER_EXECUTABLE to choose a browser.
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "../..");
const require = createRequire(path.join(root, "web/package.json"));
const { chromium } = require("playwright");

const file = (relative) => pathToFileURL(path.join(root, relative)).href;
const query = new URLSearchParams({
  still: "1",
  p5: file("node_modules/p5/lib/p5.min.js"),
  brush: file("node_modules/p5.brush/dist/p5.brush.js"),
  font: file("node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2"),
});
const executablePath = process.env.PAPERSEEK_BROWSER_EXECUTABLE
  || (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined);
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const page = await browser.newPage({ viewport: { width: 1200, height: 420 }, deviceScaleFactor: 2 });
await page.goto(`${file("docs/public/hero-painting.html")}?${query}`);
await page.waitForFunction(() => document.documentElement.dataset.hero === "done", null, { timeout: 60000 });
await page.screenshot({ path: path.join(root, "docs/public/images/hero.jpg"), type: "jpeg", quality: 86 });
await browser.close();
