import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Documentation screenshots and site checks; not part of the app browser test suite.
export default defineConfig({ ...base, testDir: "tests/docs" });
