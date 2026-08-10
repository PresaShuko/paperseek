<script setup lang="ts">
import { computed, onMounted } from "vue";

import { useLocale } from "../../locales";
import { loadCitationMap, runState } from "../../state/run";

const { t } = useLocale();
onMounted(() => loadCitationMap().catch(() => undefined));

const positioned = computed(() => {
  const nodes = runState.citationMap?.nodes || [];
  return nodes.map((node, index) => {
    const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2 - Math.PI / 2;
    return { ...node, x: 320 + Math.cos(angle) * 220, y: 230 + Math.sin(angle) * 150 };
  });
});

function point(id: string): { x: number; y: number } {
  return positioned.value.find((node) => node.id === id) || { x: 320, y: 230 };
}
</script>

<template>
  <main class="workspace-view">
    <header class="workspace-header">
      <div><div class="section-kicker">{{ t("citationMap") }}</div><h2>{{ runState.run?.question || t("noRun") }}</h2></div>
      <div v-if="runState.citationMap" class="citation-controls">
        <strong>{{ runState.citationMap.nodes.length }} {{ t("nodes") }}</strong>
        <span>{{ runState.citationMap.edges.length }} {{ t("edges") }}</span>
      </div>
    </header>
    <p v-if="!runState.citationMap" class="m4-empty">{{ t("noRun") }}</p>
    <section v-else class="citation-layout">
      <div class="citation-map-panel">
        <div class="citation-graph">
          <svg viewBox="0 0 640 460" role="img" :aria-label="t('citationMap')">
            <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>
            <line
              v-for="edge in runState.citationMap.edges"
              :key="`${edge.source}-${edge.target}`"
              class="citation-edge"
              :x1="point(edge.source).x" :y1="point(edge.source).y"
              :x2="point(edge.target).x" :y2="point(edge.target).y"
              marker-end="url(#arrow)"
            />
            <g v-for="node in positioned" :key="node.id" class="citation-node result" :transform="`translate(${node.x} ${node.y})`">
              <circle class="citation-node-mark" r="10" />
              <text x="14" y="4">{{ node.rank ? `#${node.rank}` : "•" }}</text>
            </g>
          </svg>
        </div>
      </div>
      <aside class="citation-detail">
        <article v-for="node in positioned" :key="node.id" class="m4-citation-item">
          <h3>{{ node.title }}</h3><p>{{ node.year }} · {{ node.source }} · {{ node.citations || 0 }} {{ t("citations") }}</p>
        </article>
      </aside>
    </section>
  </main>
</template>
