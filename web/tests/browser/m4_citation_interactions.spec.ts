import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const fixtureRoot = resolve(import.meta.dirname, "../../../tests/fixtures/golden_search");
const citationMap = JSON.parse(readFileSync(resolve(fixtureRoot, "citation_map.json"), "utf8"));
const runId = "77777777-7777-4777-8777-777777777777";
const run = {
  id: runId,
  question: "citation interaction behavior",
  source: "openalex",
  status: "completed",
  result_count: 5,
  warnings: [],
  created_at: "2026-08-12T00:00:00Z",
  finished_at: "2026-08-12T00:01:00Z",
};

test("citation map supports wheel zoom, pan, node drag/select, legend and seed focus", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/v1/runs/${runId}`) await route.fulfill({ json: run });
    else if (path === `/api/v1/runs/${runId}/citation-map`) await route.fulfill({ json: citationMap });
    else await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto(`/runs/${runId}/citation-map`);
  const graph = page.getByTestId("citation-graph");
  const viewport = page.getByTestId("citation-viewport");
  await expect(page.getByRole("list", { name: "Citation legend" })).toContainText("Seed");
  await expect(page.getByTestId("graph-node")).toHaveCount(citationMap.nodes.length);

  const initialZoom = Number(await viewport.getAttribute("data-zoom"));
  await graph.hover({ position: { x: 300, y: 220 } });
  await page.mouse.wheel(0, -240);
  await expect.poll(async () => Number(await viewport.getAttribute("data-zoom"))).toBeGreaterThan(initialZoom);

  const box = await graph.boundingBox();
  if (!box) throw new Error("graph_not_visible");
  await page.mouse.move(box.x + 20, box.y + 20);
  await page.mouse.down();
  await page.mouse.move(box.x + 65, box.y + 55, { steps: 4 });
  await page.mouse.up();
  await expect(viewport).not.toHaveAttribute("data-pan-x", "0");

  const node = page.getByTestId("graph-node").first();
  const before = await node.getAttribute("transform");
  const nodeBox = await node.boundingBox();
  if (!nodeBox) throw new Error("node_not_visible");
  await page.mouse.move(nodeBox.x + nodeBox.width / 2, nodeBox.y + nodeBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(nodeBox.x + nodeBox.width / 2 + 35, nodeBox.y + nodeBox.height / 2 + 20, { steps: 4 });
  await page.mouse.up();
  await expect.poll(() => node.getAttribute("transform")).not.toBe(before);

  await page.getByRole("button", { name: "Reset graph" }).click();
  await expect(viewport).toHaveAttribute("data-zoom", "1");
  await expect(viewport).toHaveAttribute("data-pan-x", "0");

  await node.click();
  await expect(page.getByTestId("citation-detail")).toContainText(citationMap.nodes[0].title);
  await expect(page.getByTestId("citation-detail")).toContainText(citationMap.nodes[0].reasoning);

  await page.getByLabel("Seed focus").selectOption(citationMap.nodes[0].id);
  await expect(page.getByTestId("graph-node")).toHaveCount(3);
  await page.getByRole("button", { name: citationMap.nodes[0].title, exact: true }).click();
  await expect(page.getByTestId("citation-detail")).toContainText(citationMap.nodes[0].title);
});
