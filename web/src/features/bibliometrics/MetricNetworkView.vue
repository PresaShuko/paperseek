<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import Icon from "../../components/Icon.vue";
import { useUi } from "../../locales/ui";
import type { MetricNetwork } from "./api";
import { useMetricMessages } from "./messages";

const props = defineProps<{ network: MetricNetwork; sourceRunId: string }>();
const { m } = useMetricMessages();
const u = useUi();
const W = 720;
const H = 380;
// Chart blues only: components alternate through the design's chart scale.
const colors = ["#155dfc", "#8ec5ff", "#193cb8", "#2b7fff", "#1447e6"];
const positions = ref<Record<string, { x: number; y: number }>>({});
const find = ref("");
const selected = ref("");
const zoom = ref(1);
const pan = ref({ x: 0, y: 0 });
const layoutError = ref(false);
const retry = ref(0);
let worker: Worker | undefined;
let drag: { x: number; y: number; originX: number; originY: number } | undefined;
const matches = computed(() => (find.value.trim()
  ? props.network.nodes.filter((node) => node.label.toLocaleLowerCase().includes(find.value.trim().toLocaleLowerCase())).slice(0, 8)
  : []));
const selectedNode = computed(() => props.network.nodes.find((node) => node.id === selected.value));
const related = computed(() => props.network.edges
  .filter((edge) => edge.source === selected.value || edge.target === selected.value)
  .sort((a, b) => b.weight - a.weight)
  .map((edge) => ({ edge, node: props.network.nodes.find((node) => node.id === (edge.source === selected.value ? edge.target : edge.source)) })));
const point = (id: string) => positions.value[id] || { x: W / 2, y: H / 2 };
const radius = (count: number) => Math.min(17, 5 + Math.sqrt(count));
function reset() {
  zoom.value = 1;
  pan.value = { x: 0, y: 0 };
}
function start(event: PointerEvent) {
  if ((event.target as Element).closest('[role="button"]')) return;
  (event.currentTarget as Element).setPointerCapture(event.pointerId);
  drag = { x: event.clientX, y: event.clientY, originX: pan.value.x, originY: pan.value.y };
}
function move(event: PointerEvent) {
  if (!drag) return;
  const scale = W / (event.currentTarget as Element).getBoundingClientRect().width;
  pan.value = { x: drag.originX + (event.clientX - drag.x) * scale, y: drag.originY + (event.clientY - drag.y) * scale };
}
function choose(id: string) {
  selected.value = id;
  find.value = "";
}
watch([() => props.network, retry], ([data]) => {
  worker?.terminate();
  selected.value = data.nodes[0]?.id || "";
  reset();
  layoutError.value = false;
  positions.value = Object.fromEntries(data.nodes.map((node, i) => [node.id, {
    x: W / 2 + 150 * Math.cos((i * 2 * Math.PI) / data.nodes.length), y: H / 2 + 130 * Math.sin((i * 2 * Math.PI) / data.nodes.length),
  }]));
  try {
    const current = new Worker(new URL("./network-layout.worker.ts", import.meta.url), { type: "module" });
    worker = current;
    current.onmessage = (event: MessageEvent<{ id: string; x: number; y: number }[]>) => {
      if (worker !== current) return;
      const rows = event.data;
      const minX = Math.min(...rows.map((p) => p.x)), maxX = Math.max(...rows.map((p) => p.x));
      const minY = Math.min(...rows.map((p) => p.y)), maxY = Math.max(...rows.map((p) => p.y));
      const scale = Math.min((W - 80) / Math.max(1, maxX - minX), (H - 60) / Math.max(1, maxY - minY));
      positions.value = Object.fromEntries(rows.map((p) => [p.id, { x: W / 2 + (p.x - (minX + maxX) / 2) * scale, y: H / 2 + (p.y - (minY + maxY) / 2) * scale }]));
      current.terminate();
    };
    current.onerror = () => {
      if (worker === current) layoutError.value = true;
      current.terminate();
    };
    current.postMessage({
      nodes: data.nodes.map((node) => ({ id: node.id, count: node.count })),
      edges: data.edges.map((edge) => ({ source: edge.source, target: edge.target, weight: edge.weight })),
    });
  } catch {
    worker?.terminate();
    layoutError.value = true;
  }
}, { immediate: true });
onBeforeUnmount(() => worker?.terminate());
</script>

<template>
  <div style="display: flex; flex-wrap: wrap; gap: 16px; align-items: stretch">
    <section class="card flush" style="flex: 999 1 560px" :aria-label="m(network.parameters.kind)">
      <div class="toolbar" style="padding: 8px 8px 8px 16px; border-bottom: 1px solid var(--border)">
        <span class="xs muted num">{{ m("displayed") }} {{ network.nodes.length }} / {{ network.eligible_node_count }} {{ m("nodes") }} · {{ network.edges.length }} / {{ network.total_edge_count }} {{ m("edges") }}<template v-if="network.excluded_reference_count"> · {{ m("excluded") }} {{ network.excluded_reference_count }}</template></span>
        <div class="row end" style="gap: 4px">
          <div class="btn-group">
            <button class="btn btn-outline btn-icon btn-sm" type="button" :aria-label="u('zoomOut')" @click="zoom = Math.max(0.4, zoom / 1.2)"><Icon name="minus" /></button>
            <button class="btn btn-outline btn-sm" type="button" @click="reset">{{ u("resetView") }}</button>
            <button class="btn btn-outline btn-icon btn-sm" type="button" :aria-label="u('zoomIn')" @click="zoom = Math.min(3, zoom * 1.2)"><Icon name="plus" /></button>
          </div>
        </div>
      </div>
      <div v-if="layoutError" class="alert" role="alert" style="margin: 12px"><Icon name="fail" /><p class="alert-title">{{ m("error") }}</p><div class="alert-act"><button class="btn btn-outline btn-sm" type="button" @click="retry++">{{ m("retry") }}</button></div></div>
      <svg class="graph" :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="m(network.parameters.kind)" @pointerdown="start" @pointermove="move" @pointerup="drag = undefined" @pointercancel="drag = undefined">
        <g :transform="`translate(${pan.x + (W / 2) * (1 - zoom)},${pan.y + (H / 2) * (1 - zoom)}) scale(${zoom})`">
          <line
            v-for="edge in network.edges"
            :key="`${edge.source}:${edge.target}`"
            :x1="point(edge.source).x" :y1="point(edge.source).y" :x2="point(edge.target).x" :y2="point(edge.target).y"
            :stroke="selected === edge.source || selected === edge.target ? '#a3a3a3' : '#e5e5e5'"
            :stroke-width="selected === edge.source || selected === edge.target ? 2.5 : 1.5"
          />
          <circle v-if="selectedNode" :cx="point(selectedNode.id).x" :cy="point(selectedNode.id).y" :r="radius(selectedNode.count) + 6" fill="none" stroke="#000" stroke-opacity=".25" stroke-width="2" />
          <g
            v-for="node in network.nodes"
            :key="node.id"
            role="button"
            tabindex="0"
            :aria-label="`${node.label}, ${node.count}`"
            :aria-pressed="selected === node.id"
            @click="selected = node.id"
            @keydown.enter="selected = node.id"
            @keydown.space.prevent="selected = node.id"
          >
            <circle :cx="point(node.id).x" :cy="point(node.id).y" :r="radius(node.count)" :fill="colors[((node.group || 1) - 1) % colors.length]" stroke="#fff" stroke-width="2" />
            <text
              v-if="network.nodes.length <= 35 || selected === node.id || radius(node.count) >= 12"
              :x="point(node.id).x" :y="point(node.id).y + radius(node.count) + 14"
              font-family="Geist Variable, sans-serif" font-size="12" fill="#262626" text-anchor="middle"
            >{{ node.label.length > 28 ? `${node.label.slice(0, 28)}…` : node.label }}</text>
            <title>{{ node.label }}</title>
          </g>
        </g>
      </svg>
    </section>
    <aside class="card c" style="flex: 1 1 280px" :aria-label="u('selectedNode')">
      <div class="card-content stack" style="gap: 12px">
        <div class="stack" style="gap: 4px; position: relative">
          <div class="ig"><Icon name="search" /><input v-model="find" type="search" :placeholder="u('findNode')" :aria-label="u('findNode')" /></div>
          <div v-if="matches.length" class="pop" style="top: 40px; left: 0; right: 0">
            <button v-for="node in matches" :key="node.id" class="opt" type="button" @click="choose(node.id)"><span class="grow truncate">{{ node.label }}</span><span class="xs muted num">{{ node.count }}</span></button>
          </div>
          <p v-else-if="find.trim()" class="xs muted">{{ m("noData") }}</p>
        </div>
        <template v-if="selectedNode">
          <div class="stack" style="gap: 2px">
            <span class="xs muted">{{ u("selectedNode") }}</span>
            <h2 class="card-title">{{ selectedNode.label }}</h2>
          </div>
          <dl class="kv">
            <dt>{{ m(network.parameters.kind === "keywords" ? "keywordOccurrences" : "referenceCount") }}</dt><dd>{{ selectedNode.count }}</dd>
            <dt>{{ m("group") }}</dt><dd>{{ selectedNode.group || 1 }}</dd>
          </dl>
          <RouterLink v-if="network.parameters.kind === 'coupling'" class="link sm" :to="`/runs/${sourceRunId}/results`">{{ m("sourceRecord") }}</RouterLink>
          <div class="sep"></div>
          <span class="xs muted medium">{{ m("connections") }}</span>
          <div class="list" style="margin: -4px -10px 0; max-height: 240px; overflow-y: auto">
            <button v-for="row in related" :key="`${row.edge.source}:${row.edge.target}`" class="list-row" type="button" @click="selected = row.node?.id || ''">
              <span class="grow sm truncate">{{ row.node?.label }}</span><span class="xs muted num">{{ row.edge.weight }} · {{ row.edge.similarity.toFixed(2) }}</span>
            </button>
          </div>
        </template>
      </div>
    </aside>
  </div>
</template>
