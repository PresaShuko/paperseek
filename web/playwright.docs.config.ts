import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Documentation screenshots only; not part of the browser test suite.
export default defineConfig({ ...base, testDir: "tests/docs" });
