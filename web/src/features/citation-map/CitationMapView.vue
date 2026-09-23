<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api } from "../../api/client";
import type { CitationMap, CitationNode, RunDetail } from "../../api/types";
import { useLocale } from "../../locales";
import { GRAPH_HEIGHT, GRAPH_WIDTH, layoutCitationMap, nodeRadius } from "./citation-layout";

type NodeRole = "result" | "seed" | "forward" | "backward";

const props = defineProps<{ snapshot?: { run: RunDetail; citationMap: CitationMap } }>();
const { sourceName, t } = useLocale();
const route = useRoute();
const runId = computed(() => String(route.params.runId || ""));
const run = ref<RunDetail | null>(null);
const citationMap = ref<CitationMap | null>(null);
const pageState = ref<"loading" | "error" | "loaded">("loading");
const selectedId = ref("");
const focusId = ref("");
const hoveredId = ref("");
const focusedNodeId = ref("");
const zoom = ref(1);
const pan = reactive({ x: 0, y: 0 });
// User drags persist across zoom resets and seed-focus changes (§10.3).
const positions = ref<Record<string, { x: number; y: number }>>({});
let pointer: { id: number; mode: "pan" | "node"; nodeId?: string; x: number; y: number; moved: boolean } | null = null;
let generation = 0;
let controller: AbortController | null = null;

const seeds = computed(() => (citationMap.value?.nodes || []).filter((node) => node.roles?.includes("seed")));
const visibleIds = computed(() => {
  if (!focusId.value || !citationMap.value) return null;
  const ids = new Set([focusId.value]);
  for (const edge of citationMap.value.edges || []) {
    if (edge.source === focusId.value) ids.add(edge.target);
    if (edge.target === focusId.value) ids.add(edge.source);
  }
  return ids;
});
const nodes = computed(() => (citationMap.value?.nodes || []).filter((node) => !visibleIds.value || visibleIds.value.has(node.id)));
const edges = computed(() => (citationMap.value?.edges || []).filter((edge) => nodes.value.some((node) => node.id === edge.source) && nodes.value.some((node) => node.id === edge.target)));
const selected = computed(() => citationMap.value?.nodes?.find((node) => node.id === selectedId.value) || null);

// Empty states are classified, never a blank canvas (§10.4).
const emptyState = computed(() => {
  const map = citationMap.value;
  if (!map) return "";
  if (map["enabled"] === false) return "citationNotEnabled";
  if (map["supported"] === false) return "citationNotSupported";
  if (!(map.nodes || []).length) return "citationEmpty";
  return "";
});

const metricsLine = computed(() => {
  const map = citationMap.value;
  if (!map) return "";
  const parts: string[] = [];
  if (typeof map["seed_count"] === "number") parts.push(`${map["seed_count"]} ${t("seedsCount")}`);
  if (typeof map["added_candidates"] === "number") parts.push(`${map["added_candidates"]} ${t("citationAdded")}`);
  return parts.join(" · ");
});

// Color and shape together encode the role; legend glyphs use the same geometry.
function primaryRole(node: CitationNode): NodeRole {
  const roles = node.roles || [];
  if (roles.includes("seed")) return "seed";
  if (roles.includes("forward")) return "forward";
  if (roles.includes("backward")) return "backward";
  return "result";
}

const legend: Array<{ role: NodeRole; label: string }> = [
  { role: "result", label: "resultNode" },
  { role: "seed", label: "seedNode" },
  { role: "forward", label: "forwardNode" },
  { role: "backward", label: "backwardNode" },
];

function radius(node: CitationNode): number {
  return nodeRadius(node.citations);
}

function shapePath(role: NodeRole, r: number): string {
  if (role === "forward") return `M0 ${-r} L${r} ${r} L${-r} ${r} Z`;
  if (role === "backward") return `M0 ${-r} L${r} 0 L0 ${r} L${-r} 0 Z`;
  return "";
}

function shortTitle(node: CitationNode): string {
  const title = node.title || "";
  return title.length > 28 ? `${title.slice(0, 28)}…` : title;
}

function showLabel(node: CitationNode): boolean {
  return primaryRole(node) === "seed"
    || selectedId.value === node.id
    || hoveredId.value === node.id
    || focusedNodeId.value === node.id
    || zoom.value >= 1.5;
}

function nodeLabel(node: CitationNode): string {
  if (showLabel(node)) return shortTitle(node);
  return node.rank ? `#${node.rank}` : "";
}

function roleLabel(node: CitationNode): string {
  return t(legend.find((entry) => entry.role === primaryRole(node))?.label || "resultNode");
}

function resetGraph(): void {
  // Reset restores the viewport only; dragged node positions are kept (§10.3).
  zoom.value = 1;
  pan.x = 0;
  pan.y = 0;
}

function point(id: string): { x: number; y: number } {
  return positions.value[id] || { x: GRAPH_WIDTH / 2, y: GRAPH_HEIGHT / 2 };
}

function clampZoom(value: number): number {
  return Math.min(2.5, Math.max(0.5, Number(value.toFixed(3))));
}

function onWheel(event: WheelEvent): void {
  zoom.value = clampZoom(zoom.value * (event.deltaY < 0 ? 1.12 : 0.89));
}

function onPointerDown(event: PointerEvent): void {
  pointer = {
    id: event.pointerId,
    mode: "pan",
    x: event.clientX,
    y: event.clientY,
    moved: false,
  };
  (event.currentTarget as SVGElement).setPointerCapture(event.pointerId);
}

function onNodePointerDown(event: PointerEvent, nodeId: string): void {
  pointer = { id: event.pointerId, mode: "node", nodeId, x: event.clientX, y: event.clientY, moved: false };
  const svg = (event.currentTarget as SVGGElement).ownerSVGElement;
  svg?.setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent): void {
  if (!pointer || pointer.id !== event.pointerId) return;
  const dx = event.clientX - pointer.x;
  const dy = event.clientY - pointer.y;
  if (Math.abs(dx) + Math.abs(dy) > 1) pointer.moved = true;
  if (pointer.mode === "node" && pointer.nodeId) {
    const current = point(pointer.nodeId);
    positions.value = { ...positions.value, [pointer.nodeId]: { x: current.x + dx / zoom.value, y: current.y + dy / zoom.value } };
  } else {
    pan.x += dx;
    pan.y += dy;
  }
  pointer.x = event.clientX;
  pointer.y = event.clientY;
}

function onPointerUp(event: PointerEvent): void {
  if (!pointer || pointer.id !== event.pointerId) return;
  if (pointer.mode === "node" && pointer.nodeId && !pointer.moved) selectNode(pointer.nodeId);
  pointer = null;
  (event.currentTarget as SVGElement).releasePointerCapture(event.pointerId);
}

function selectNode(id: string): void {
  selectedId.value = id;
}

function onNodeKeydown(event: KeyboardEvent, nodeId: string): void {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  selectNode(nodeId);
}

function isRecordLink(id: string): boolean {
  return /^https?:\/\//.test(id);
}

function applyMap(map: CitationMap): void {
  citationMap.value = map;
  positions.value = layoutCitationMap(map.nodes || [], map.edges || []);
  selectedId.value = seeds.value[0]?.id || map.nodes?.[0]?.id || "";
}

async function load(value: string): Promise<void> {
  if (!value) return;
  const current = ++generation;
  controller?.abort();
  controller = new AbortController();
  run.value = null;
  citationMap.value = null;
  selectedId.value = "";
  focusId.value = "";
  positions.value = {};
  pageState.value = "loading";
  if (props.snapshot?.run.id === value) {
    run.value = props.snapshot.run;
    applyMap(props.snapshot.citationMap);
    pageState.value = "loaded";
    return;
  }
  const [detail, map] = await Promise.allSettled([
    api.run(value, controller.signal),
    api.citationMap(value, controller.signal),
  ]);
  if (current !== generation || runId.value !== value) return;
  if (detail.status === "fulfilled") run.value = detail.value;
  if (map.status === "fulfilled") {
    applyMap(map.value);
    pageState.value = "loaded";
  } else {
    pageState.value = "error";
  }
}

watch(runId, (value) => void load(value), { immediate: true });

onBeforeUnmount(() => {
  generation += 1;
  controller?.abort();
});
</script>

<template>
  <div class="workspace-view">
    <header class="workspace-header">
      <div><div class="section-kicker">{{ t("citationMap") }}</div><h2>{{ run?.question || t("noRun") }}</h2></div>
      <div v-if="citationMap" class="toolbar-counts">
        <strong>{{ citationMap.nodes?.length || 0 }} {{ t("nodes") }}</strong>
        <span>{{ citationMap.edges?.length || 0 }} {{ t("edges") }}</span>
        <span v-if="metricsLine">{{ metricsLine }}</span>
      </div>
    </header>

    <div v-if="pageState === 'loading'" class="state-block" data-testid="citation-loading">
      <span>{{ t("active") }}…</span>
    </div>
    <div v-else-if="pageState === 'error'" class="state-block state-block--error" role="alert">
      <strong>{{ t("loadError") }}</strong>
      <button class="button" type="button" @click="load(runId)">{{ t("retry") }}</button>
    </div>
    <div v-else-if="!citationMap" class="state-block">{{ t("noRun") }}</div>
    <div v-else-if="emptyState" class="state-block" data-testid="citation-empty">
      <span>{{ t(emptyState) }}</span>
      <RouterLink class="button button--small" :to="`/runs/${runId}`">{{ t("backToRun") }}</RouterLink>
    </div>
    <section v-else class="citation-layout">
      <div class="citation-map-panel">
        <div class="citation-toolbar workspace-toolbar">
          <ul class="citation-legend" :aria-label="t('citationLegend')">
            <li v-for="entry in legend" :key="entry.role">
              <svg class="legend-glyph" viewBox="-8 -8 16 16" aria-hidden="true">
                <circle v-if="entry.role === 'result'" r="6" :class="`legend-shape legend-shape--${entry.role}`" />
                <rect v-else-if="entry.role === 'seed'" x="-6" y="-6" width="12" height="12" :class="`legend-shape legend-shape--${entry.role}`" />
                <path v-else :d="shapePath(entry.role, 6)" :class="`legend-shape legend-shape--${entry.role}`" />
              </svg>
              {{ t(entry.label) }}
            </li>
          </ul>
          <span class="spacer"></span>
          <button class="button button--small" type="button" :aria-label="t('zoomOut')" @click="zoom = clampZoom(zoom / 1.12)">−</button>
          <button class="button button--small" type="button" :aria-label="t('resetGraph')" @click="resetGraph">{{ t("resetGraph") }}</button>
          <button class="button button--small" type="button" :aria-label="t('zoomIn')" @click="zoom = clampZoom(zoom * 1.12)">+</button>
          <label class="field">
            <span class="sr-only">{{ t("seedFocus") }}</span>
            <select v-model="focusId" :aria-label="t('seedFocus')"><option value="">{{ t("allSeeds") }}</option><option v-for="seed in seeds" :key="seed.id" :value="seed.id">{{ seed.title }}</option></select>
          </label>
        </div>
        <div class="citation-graph" data-testid="citation-graph">
          <svg :viewBox="`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`" role="img" :aria-label="t('citationMap')" @wheel.prevent="onWheel" @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp" @pointercancel="onPointerUp">
            <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>
            <g data-testid="citation-viewport" :data-zoom="zoom" :data-pan-x="pan.x" :data-pan-y="pan.y" :transform="`translate(${pan.x} ${pan.y}) scale(${zoom})`">
              <line v-for="edge in edges" :key="`${edge.source}-${edge.target}`" class="citation-edge" :x1="point(edge.source).x" :y1="point(edge.source).y" :x2="point(edge.target).x" :y2="point(edge.target).y" marker-end="url(#arrow)" />
              <g
                v-for="node in nodes"
                :key="node.id"
                class="citation-node"
                data-testid="graph-node"
                :data-node-id="node.id"
                :data-role="primaryRole(node)"
                :data-selected="selectedId === node.id"
                :transform="`translate(${point(node.id).x} ${point(node.id).y})`"
                tabindex="0"
                role="button"
                :aria-label="`${t('selectNode')}: ${node.title}`"
                :aria-pressed="selectedId === node.id"
                @pointerdown.stop="onNodePointerDown($event, node.id)"
                @pointerenter="hoveredId = node.id"
                @pointerleave="hoveredId = ''"
                @focus="focusedNodeId = node.id"
                @blur="focusedNodeId = ''"
                @keydown="onNodeKeydown($event, node.id)"
              >
                <circle class="citation-hit-target" :r="Math.max(radius(node) + 8, 18)" />
                <circle v-if="primaryRole(node) === 'result'" class="citation-node-shape" :r="radius(node)" />
                <rect v-else-if="primaryRole(node) === 'seed'" class="citation-node-shape" :x="-radius(node)" :y="-radius(node)" :width="radius(node) * 2" :height="radius(node) * 2" :rx="2" />
                <path v-else class="citation-node-shape" :d="shapePath(primaryRole(node), radius(node))" />
                <text v-if="nodeLabel(node)" class="citation-node-label" :class="{ 'citation-node-label--title': showLabel(node) }" x="0" :y="radius(node) + 14" text-anchor="middle">{{ nodeLabel(node) }}</text>
              </g>
            </g>
          </svg>
        </div>
      </div>
      <aside class="citation-detail-panel">
        <article v-if="selected" class="citation-detail-card" data-testid="citation-detail">
          <h3>{{ selected.title }}</h3>
          <p class="detail-meta">{{ [selected.source ? sourceName(selected.source, selected.source) : "", selected.year, `${selected.citations || 0} ${t('citations')}`].filter((value) => value !== "" && value !== null && value !== undefined).join(" · ") }}</p>
          <p><span class="detail-label">{{ t("citationRole") }}</span> {{ roleLabel(selected) }}</p>
          <p data-testid="citation-detail-score"><span class="detail-label">{{ t("sortScore") }}</span> {{ selected.score !== null && selected.score !== undefined ? `${selected.score}/10` : t("notScored") }}</p>
          <p v-if="selected.reasoning">{{ selected.reasoning }}</p>
          <a v-if="isRecordLink(selected.id)" :href="selected.id" target="_blank" rel="noopener">{{ t("record") }}</a>
        </article>
        <details class="citation-text-equivalent" data-testid="citation-text-list">
          <summary>{{ t("citationTextList") }}</summary>
          <section class="citation-text-list">
            <h3>{{ t("seedPapers") }}</h3>
            <button v-for="seed in seeds" :key="seed.id" class="node-button" type="button" :aria-label="seed.title" :aria-pressed="selectedId === seed.id" @click="selectNode(seed.id)">{{ seed.title }}</button>
          </section>
          <section class="citation-text-list">
            <button v-for="node in nodes" :key="`text-${node.id}`" class="node-button" type="button" :aria-label="`${t('selectNode')}: ${node.title}`" :aria-pressed="selectedId === node.id" @click="selectNode(node.id)">{{ node.title }}</button>
          </section>
        </details>
      </aside>
    </section>
  </div>
</template>
