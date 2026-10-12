import { createRouter, createWebHistory } from "vue-router";

import CitationMapView from "./features/citation-map/CitationMapView.vue";
import HistoryView from "./features/history/HistoryView.vue";
import ResultsView from "./features/results/ResultsView.vue";
import SearchWorkspace from "./features/search/SearchWorkspace.vue";

// Each module's nav entry opens its create page; "All" opens its record list.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/search" },
    { path: "/settings", redirect: "/settings/models" },
    { path: "/settings/:section(models|sources|general|user)", name: "settings", component: () => import("./features/workspace/WorkspacePreferences.vue") },
    { path: "/search", name: "search", component: SearchWorkspace, props: { mode: "edit" } },
    { path: "/runs/:runId", name: "run", component: SearchWorkspace, props: { mode: "run" } },
    { path: "/runs/:runId/results", name: "results", component: ResultsView, props: { reviewsEnabled: true } },
    { path: "/runs/:runId/citation-map", name: "citation-map", component: CitationMapView },
    { path: "/history", name: "history", component: HistoryView },
    { path: "/bibliometrics", name: "bibliometrics", component: () => import("./features/bibliometrics/BiblioNew.vue") },
    { path: "/bibliometrics/history", name: "analyses", component: () => import("./features/bibliometrics/AnalysisList.vue") },
    { path: "/bibliometrics/:analysisId", name: "analysis", component: () => import("./features/bibliometrics/AnalysisWorkspace.vue") },
    { path: "/reviews", name: "reviews", component: () => import("./features/review/ReviewList.vue") },
    { path: "/reviews/new", name: "review-new", component: () => import("./features/review/ReviewCreate.vue") },
    { path: "/reviews/:reviewId", name: "review", component: () => import("./features/review/ReviewWorkspace.vue") },
  ],
});

// After an upgrade, an open tab may ask for page chunks that no longer exist.
// Load the target with a full navigation so the new build is used instead.
router.onError((error, to) => {
  if (/dynamically imported module|Importing a module script failed|error loading dynamically imported/i.test(String(error?.message || error)))
    window.location.assign(to.fullPath);
});
