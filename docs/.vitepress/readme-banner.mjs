// Render the README banner from readme-banner.html in English and Chinese.
//   node docs/.vitepress/readme-banner.mjs
// Uses the web package's Playwright; set PAPERSEEK_BROWSER_EXECUTABLE to choose a browser.
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "../../web/package.json"));
const { chromium } = require("playwright");

const executablePath = process.env.PAPERSEEK_BROWSER_EXECUTABLE
  || (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined);
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const page = await browser.newPage({ viewport: { width: 1600, height: 800 }, deviceScaleFactor: 1.25 });
const source = pathToFileURL(path.join(here, "readme-banner.html")).href;
for (const lang of ["en", "zh"]) {
  await page.goto(`${source}?lang=${lang}`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(here, `../public/images/readme-banner-${lang}.png`) });
}
await browser.close();
