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
  await page.getByTestId("citation-text-list").getByText("Text list").click();
  await page.getByRole("button", { name: citationMap.nodes[0].title, exact: true }).click();
  await expect(page.getByTestId("citation-detail")).toContainText(citationMap.nodes[0].title);
});

test("force layout is stable, legend glyphs match node shapes and seed labels show", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/v1/runs/${runId}`) await route.fulfill({ json: run });
    else if (path === `/api/v1/runs/${runId}/citation-map`) await route.fulfill({ json: citationMap });
    else await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });

  await page.goto(`/runs/${runId}/citation-map`);
  await expect(page.getByTestId("graph-node")).toHaveCount(citationMap.nodes.length);

  // Force layout: nodes spread across the canvas instead of sharing one ring.
  const transforms = await page.getByTestId("graph-node").evaluateAll((elements) =>
    elements.map((element) => {
      const match = /translate\(([-\d.]+) ([-\d.]+)\)/.exec(element.getAttribute("transform") || "");
      return match ? { x: Number(match[1]), y: Number(match[2]) } : { x: 0, y: 0 };
    }));
  const distances = transforms.map((point) => Math.hypot(point.x - 320, point.y - 230));
  const min = Math.min(...distances);
  const max = Math.max(...distances);
  expect(max - min).toBeGreaterThan(40);

  // Layout is deterministic: a reload reproduces the same positions.
  const original = await page.getByTestId("graph-node").evaluateAll((elements) => elements.map((element) => element.getAttribute("transform")));
  await page.reload();
  const reloaded = await page.getByTestId("graph-node").evaluateAll((elements) => elements.map((element) => element.getAttribute("transform")));
  expect(reloaded).toEqual(original);

  // Legend glyphs use the same element kind as the node shape per role.
  const legendShapes = await page.getByRole("list", { name: "Citation legend" }).locator("svg.legend-glyph > *").evaluateAll(
    (elements) => elements.map((element) => element.tagName),
  );
  expect(legendShapes).toEqual(["circle", "rect", "path", "path"]);
  for (const [role, tag] of [["result", "circle"], ["seed", "rect"], ["forward", "path"], ["backward", "path"]] as const) {
    const shapeTag = await page.locator(`.citation-node[data-role="${role}"] .citation-node-shape`).first().evaluate((element) => element.tagName);
    expect(shapeTag.toLowerCase()).toBe(tag);
  }

  // Seeds show a short title by default; rankless nodes never show a dash row.
  const seed = citationMap.nodes.find((node: { roles?: string[] }) => node.roles?.includes("seed"));
  const seedNode = page.locator(`.citation-node[data-node-id="${seed.id}"]`);
  await expect(seedNode.locator("text")).toContainText(seed.title.slice(0, 28));
  const rankless = page.locator(`.citation-node[data-role="forward"] text`, { hasText: "—" });
  await expect(rankless).toHaveCount(0);

  // The first seed is the default detail selection.
  await expect(page.getByTestId("citation-detail")).toContainText(seed.title);
});

test("citation map classifies empty states instead of a blank canvas", async ({ page }) => {
  const cases = [
    { map: { enabled: false, supported: true, nodes: [], edges: [] }, text: "Citation expansion was not enabled for this run." },
    { map: { enabled: true, supported: false, nodes: [], edges: [] }, text: "This source does not support citation traversal." },
    { map: { enabled: true, supported: true, status: "complete", nodes: [], edges: [] }, text: "No citation data is available yet." },
  ];
  for (const entry of cases) {
    await page.unrouteAll();
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === `/api/v1/runs/${runId}`) await route.fulfill({ json: run });
      else if (path === `/api/v1/runs/${runId}/citation-map`) await route.fulfill({ json: entry.map });
      else await route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
    });
    await page.goto(`/runs/${runId}/citation-map`);
    await expect(page.getByTestId("citation-empty")).toContainText(entry.text);
    await expect(page.getByTestId("graph-node")).toHaveCount(0);
  }
});
