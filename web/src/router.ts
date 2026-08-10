import { createRouter, createWebHistory } from "vue-router";

import CitationMapView from "./features/citation-map/CitationMapView.vue";
import HistoryView from "./features/history/HistoryView.vue";
import ResultsView from "./features/results/ResultsView.vue";
import SearchView from "./features/search/SearchView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "search", component: SearchView },
    { path: "/results", name: "results", component: ResultsView },
    { path: "/citation-map", name: "citation-map", component: CitationMapView },
    { path: "/history", name: "history", component: HistoryView },
  ],
});
