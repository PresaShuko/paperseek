<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api } from "../../api/client";
import type { CitationMap, CitationNode, RunDetail } from "../../api/types";
import { useLocale } from "../../locales";

const props = defineProps<{ snapshot?: { run: RunDetail; citationMap: CitationMap } }>();
const { sourceName, t } = useLocale();
const route = useRoute();
const runId = computed(() => String(route.params.runId || ""));
const run = ref<RunDetail | null>(null);
const citationMap = ref<CitationMap | null>(null);
const pageState = ref<"loading" | "error" | "loaded">("loading");
const selectedId = ref("");
const focusId = ref("");
const zoom = ref(1);
const pan = reactive({ x: 0, y: 0 });
const positions = reactive<Record<string, { x: number; y: number }>>({});
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

function nodeRole(node: CitationNode): string {
  return (node.roles || []).join(" ");
}

function resetPositions(): void {
  for (const key of Object.keys(positions)) delete positions[key];
  const all = citationMap.value?.nodes || [];
  all.forEach((node, index) => {
    const angle = (index / Math.max(1, all.length)) * Math.PI * 2 - Math.PI / 2;
    positions[node.id] = { x: 320 + Math.cos(angle) * 220, y: 230 + Math.sin(angle) * 150 };
  });
}

function resetGraph(): void {
  zoom.value = 1;
  pan.x = 0;
  pan.y = 0;
  resetPositions();
}

function point(id: string): { x: number; y: number } {
  return positions[id] || { x: 320, y: 230 };
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
    positions[pointer.nodeId] = { x: current.x + dx / zoom.value, y: current.y + dy / zoom.value };
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

async function load(value: string): Promise<void> {
  if (!value) return;
  const current = ++generation;
  controller?.abort();
  controller = new AbortController();
  run.value = null;
  citationMap.value = null;
  selectedId.value = "";
  focusId.value = "";
  pageState.value = "loading";
  if (props.snapshot?.run.id === value) {
    run.value = props.snapshot.run;
    citationMap.value = props.snapshot.citationMap;
    resetGraph();
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
    citationMap.value = map.value;
    resetGraph();
    pageState.value = "loaded";
  } else {
    pageState.value = "error";
  }
}

watch(runId, (value) => void load(value), { immediate: true });

watch(focusId, resetGraph);

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
    <section v-else class="citation-layout">
      <div class="citation-map-panel">
        <div class="citation-toolbar">
          <ul class="citation-legend" :aria-label="t('citationLegend')">
            <li><span class="legend-mark legend-mark--result" aria-hidden="true"></span>{{ t("resultNode") }}</li>
            <li><span class="legend-mark legend-mark--seed" aria-hidden="true"></span>{{ t("seedNode") }}</li>
            <li><span class="legend-mark legend-mark--forward" aria-hidden="true"></span>{{ t("forwardNode") }}</li>
            <li><span class="legend-mark legend-mark--backward" aria-hidden="true"></span>{{ t("backwardNode") }}</li>
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
          <svg viewBox="0 0 640 460" role="img" :aria-label="t('citationMap')" @wheel.prevent="onWheel" @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp" @pointercancel="onPointerUp">
            <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>
            <g data-testid="citation-viewport" :data-zoom="zoom" :data-pan-x="pan.x" :data-pan-y="pan.y" :transform="`translate(${pan.x} ${pan.y}) scale(${zoom})`">
              <line v-for="edge in edges" :key="`${edge.source}-${edge.target}`" class="citation-edge" :x1="point(edge.source).x" :y1="point(edge.source).y" :x2="point(edge.target).x" :y2="point(edge.target).y" marker-end="url(#arrow)" />
              <g
                v-for="node in nodes"
                :key="node.id"
                class="citation-node"
                data-testid="graph-node"
                :data-node-id="node.id"
                :data-role="nodeRole(node)"
                :data-selected="selectedId === node.id"
                :transform="`translate(${point(node.id).x} ${point(node.id).y})`"
                tabindex="0"
                role="button"
                :aria-label="`${t('selectNode')}: ${node.title}`"
                :aria-pressed="selectedId === node.id"
                @pointerdown.stop="onNodePointerDown($event, node.id)"
                @keydown="onNodeKeydown($event, node.id)"
              >
                <circle class="citation-hit-target" r="18" />
                <circle class="citation-node-mark" r="10" />
                <text x="14" y="4">{{ node.rank ? `#${node.rank}` : "—" }}</text>
              </g>
            </g>
          </svg>
        </div>
      </div>
      <aside class="citation-detail-panel">
        <article v-if="selected" class="citation-detail-card" data-testid="citation-detail">
          <h3>{{ selected.title }}</h3>
          <p class="detail-meta">{{ [selected.year, selected.source ? sourceName(selected.source, selected.source) : "", `${selected.citations || 0} ${t('citations')}`].filter(Boolean).join(' · ') }}</p>
          <p v-if="selected.score !== undefined">{{ t("sortScore") }}: {{ selected.score }}</p>
          <p v-if="selected.rank">{{ t("sortRank") }}: {{ selected.rank }}</p>
          <p v-if="selected.reasoning">{{ selected.reasoning }}</p>
          <a :href="selected.id" target="_blank" rel="noopener">{{ t("record") }}</a>
        </article>
        <section class="citation-text-list">
          <h3>{{ t("seedPapers") }}</h3>
          <button v-for="seed in seeds" :key="seed.id" class="node-button" type="button" :aria-label="seed.title" :aria-pressed="selectedId === seed.id" @click="selectNode(seed.id)">{{ seed.title }}</button>
        </section>
        <section class="citation-text-list">
          <button v-for="node in nodes" :key="`text-${node.id}`" class="node-button" type="button" :aria-label="`${t('selectNode')}: ${node.title}`" :aria-pressed="selectedId === node.id" @click="selectNode(node.id)">{{ node.title }}</button>
        </section>
      </aside>
    </section>
  </div>
</template>
