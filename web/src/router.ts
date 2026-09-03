import { createRouter, createWebHistory } from "vue-router";

import CitationMapView from "./features/citation-map/CitationMapView.vue";
import HistoryView from "./features/history/HistoryView.vue";
import ResultsView from "./features/results/ResultsView.vue";
import RunView from "./features/search/RunView.vue";
import SearchView from "./features/search/SearchView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/search" },
    { path: "/search", name: "search", component: SearchView },
    { path: "/runs/:runId", name: "run", component: RunView },
    { path: "/runs/:runId/results", name: "results", component: ResultsView },
    { path: "/runs/:runId/citation-map", name: "citation-map", component: CitationMapView },
    { path: "/history", name: "history", component: HistoryView },
  ],
});
