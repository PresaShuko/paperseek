import { createRouter, createWebHistory } from "vue-router";

import CitationMapView from "./features/citation-map/CitationMapView.vue";
import HistoryView from "./features/history/HistoryView.vue";
import ResultsView from "./features/results/ResultsView.vue";
import SearchWorkspace from "./features/search/SearchWorkspace.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/search" },
    // Both workbench routes render the same component so submission keeps the
    // layout, scroll position and left-column content continuous (§2.1).
    { path: "/search", name: "search", component: SearchWorkspace, props: { mode: "edit" } },
    { path: "/runs/:runId", name: "run", component: SearchWorkspace, props: { mode: "run" } },
    { path: "/runs/:runId/results", name: "results", component: ResultsView },
    { path: "/runs/:runId/citation-map", name: "citation-map", component: CitationMapView },
    { path: "/history", name: "history", component: HistoryView },
  ],
});
