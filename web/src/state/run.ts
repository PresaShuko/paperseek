import { reactive } from "vue";

import { api } from "../api/client";
import type { CitationMap, PaperResult, RunDetail, RunEvent, SearchSubmission } from "../api/types";

export type StageKey = "query" | "search" | "ranking" | "results";
export type StageState = "idle" | "active" | "complete" | "failed";

const state = reactive({
  run: null as RunDetail | null,
  events: [] as RunEvent[],
  results: [] as PaperResult[],
  citationMap: null as CitationMap | null,
  stages: {
    query: "idle",
    search: "idle",
    ranking: "idle",
    results: "idle",
  } as Record<StageKey, StageState>,
  error: "",
});

function stageFor(event: RunEvent): StageKey | null {
  const value = `${event.event_type} ${event.stage}`;
  if (/query/.test(value)) return "query";
  if (/retriev|citation|search/.test(value)) return "search";
  if (/rank|enrich/.test(value)) return "ranking";
  if (/final|workflow\.completed/.test(value)) return "results";
  return null;
}

function observe(event: RunEvent): void {
  state.events.push(event);
  const stage = stageFor(event);
  if (stage) state.stages[stage] = /completed|complete|final/.test(`${event.event_type} ${event.stage}`) ? "complete" : "active";
  if (event.event_type === "workflow.completed") {
    for (const key of Object.keys(state.stages) as StageKey[]) state.stages[key] = "complete";
  }
}

export async function startSearch(payload: SearchSubmission): Promise<void> {
  state.error = "";
  state.events = [];
  state.results = [];
  state.citationMap = null;
  for (const key of Object.keys(state.stages) as StageKey[]) state.stages[key] = "idle";
  try {
    const key = globalThis.crypto.randomUUID();
    state.run = await api.submit(payload, key);
    state.stages.query = "active";
    await api.events(state.run.id, observe);
    state.run = await api.run(state.run.id);
    if (state.run.status === "failed" || state.run.status === "cancelled") {
      const active = (Object.keys(state.stages) as StageKey[]).find((key) => state.stages[key] === "active");
      if (active) state.stages[active] = "failed";
    }
  } catch (error) {
    state.error = error instanceof Error ? error.message : "search_failed";
    const active = (Object.keys(state.stages) as StageKey[]).find((key) => state.stages[key] === "active");
    if (active) state.stages[active] = "failed";
  }
}

export async function loadResults(): Promise<void> {
  if (state.run) state.results = await api.results(state.run.id);
}

export async function loadCitationMap(): Promise<void> {
  if (state.run) state.citationMap = await api.citationMap(state.run.id);
}

export function selectRun(run: RunDetail): void {
  state.run = run;
  state.results = [];
  state.citationMap = null;
}

export const runState = state;
