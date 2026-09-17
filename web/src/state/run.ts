import { reactive } from "vue";

import { api } from "../api/client";
import type { RunAudit, RunDetail, RunEvent, SearchSubmission } from "../api/types";

export type StageKey = "query" | "search" | "ranking" | "results";
export type StageState = "idle" | "active" | "complete" | "failed";
export type ConnectionState = "connected" | "reconnecting" | "offline";

const state = reactive({
  run: null as RunDetail | null,
  events: [] as RunEvent[],
  audit: null as RunAudit | null,
  lastEventSequence: 0,
  connection: "offline" as ConnectionState,
  cancelPending: false,
  stages: {
    query: "idle",
    search: "idle",
    ranking: "idle",
    results: "idle",
  } as Record<StageKey, StageState>,
  // First durable event time per stage; used only to derive elapsed time (§6).
  stageStartedAt: {
    query: null,
    search: null,
    ranking: null,
    results: null,
  } as Record<StageKey, string | null>,
  error: "",
});

const terminalStatuses = new Set(["completed", "completed_with_warnings", "failed", "cancelled"]);
let recoveryGeneration = 0;
let recoveryController: AbortController | null = null;

class EventGapError extends Error {}

function stageFor(event: RunEvent): StageKey | null {
  const type = event.event_type;
  if (type === "query.started" || type === "query.planned" || type === "query.failed") return "query";
  if (type === "query.progress" || type === "query.portfolio_recorded") return "search";
  if (/^(retrieval|citation|ranking|enrichment)\./.test(type)) return "ranking";
  if (/^(final\.|workflow\.completed)/.test(type)) return "results";
  return null;
}

const stageOrder: StageKey[] = ["query", "search", "ranking", "results"];

function resetRunState(): void {
  state.run = null;
  state.events = [];
  state.audit = null;
  state.lastEventSequence = 0;
  state.error = "";
  state.cancelPending = false;
  for (const key of Object.keys(state.stages) as StageKey[]) {
    state.stages[key] = "idle";
    state.stageStartedAt[key] = null;
  }
}

function observe(runId: string, event: RunEvent): void {
  if (event.run_id !== runId) return;
  if (event.sequence <= state.lastEventSequence) return;
  if (event.sequence !== state.lastEventSequence + 1) throw new EventGapError("event_sequence_gap");
  state.events.push(event);
  state.lastEventSequence = event.sequence;
  applyLiveAudit(event);
  if (event.event_type === "run.cancelling" && state.run?.status !== "cancelled") {
    state.run = { ...state.run!, status: "cancelling", current_step: "cancelling" };
  }
  if (event.event_type === "run.cancelled") {
    state.run = { ...state.run!, status: "cancelled", current_step: "cancelled" };
    applyTerminalFailure();
    return;
  }
  if (state.run?.status === "cancelling" || state.run?.status === "cancelled") return;
  const stage = stageFor(event);
  if (stage) {
    if (!state.stageStartedAt[stage] && event.occurred_at) state.stageStartedAt[stage] = event.occurred_at;
    const index = stageOrder.indexOf(stage);
    for (const previous of stageOrder.slice(0, index)) {
      if (state.stages[previous] !== "failed") state.stages[previous] = "complete";
    }
    const failed = /failed|error/.test(`${event.event_type} ${event.stage}`);
    state.stages[stage] = failed ? "failed" : "active";
  }
  if (event.event_type === "workflow.completed") {
    for (const key of Object.keys(state.stages) as StageKey[]) state.stages[key] = "complete";
  }
}

function applyLiveAudit(event: RunEvent): void {
  const audit = state.audit || {
    query_portfolio: [],
    loop_decisions: [],
    candidate_queue: {},
    candidate_lifecycle: {},
    recovery: {},
  };
  if (event.event_type === "query.progress") {
    audit.loop_decisions = [...(audit.loop_decisions || []), { ...event.payload }];
  } else if (event.event_type === "query.portfolio_recorded") {
    audit.query_portfolio = [...(audit.query_portfolio || []), { ...event.payload }];
  } else if (event.event_type === "workflow.recovery") {
    const recovery = Object.fromEntries(
      Object.entries(event.payload || {}).map(([key, value]) => [key, Number(value) || 0]),
    );
    recovery.total = Object.values(recovery).reduce((total, value) => total + value, 0);
    audit.recovery = recovery;
  }
  state.audit = audit;
}

function isCurrent(runId: string, generation: number): boolean {
  return recoveryGeneration === generation && state.run?.id === runId;
}

function isCurrentGeneration(generation: number): boolean {
  return recoveryGeneration === generation;
}

function applySnapshot(runId: string, generation: number, snapshot: RunDetail): boolean {
  if (!isCurrent(runId, generation) || snapshot.id !== runId) return false;
  const currentStatus = state.run?.status;
  if (currentStatus === "cancelled" && snapshot.status !== "cancelled") return true;
  if (currentStatus === "cancelling" && !["cancelling", "cancelled"].includes(snapshot.status)) return true;
  state.run = snapshot;
  applyTerminalFailure();
  return true;
}

function applyTerminalFailure(): void {
  if (state.run?.status !== "failed" && state.run?.status !== "cancelled") return;
  if ((Object.keys(state.stages) as StageKey[]).some((key) => state.stages[key] === "failed")) return;
  const active = (Object.keys(state.stages) as StageKey[]).find((key) => state.stages[key] === "active");
  if (active) state.stages[active] = "failed";
}

export async function submitSearch(payload: SearchSubmission): Promise<RunDetail> {
  stopRunRecovery();
  resetRunState();
  const submitted = await api.submit(payload, globalThis.crypto.randomUUID());
  state.run = submitted;
  state.stages.query = "active";
  return submitted;
}

function delay(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

// Offline pauses reconnect churn; `online` resumes with a fresh snapshot first (§10.6).
function waitForOnline(signal?: AbortSignal | null): Promise<void> {
  if (globalThis.navigator?.onLine !== false) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      globalThis.removeEventListener("online", done);
      signal?.removeEventListener("abort", done);
      resolve();
    };
    globalThis.addEventListener("online", done, { once: true });
    signal?.addEventListener("abort", done, { once: true });
  });
}

export async function recoverRun(runId: string, loadAudit: typeof api.audit | null = api.audit): Promise<void> {
  stopRunRecovery();
  const generation = recoveryGeneration;
  const controller = new AbortController();
  recoveryController = controller;
  resetRunState();
  const initialSnapshot = await api.run(runId, controller.signal);
  if (!isCurrentGeneration(generation) || initialSnapshot.id !== runId) return;
  state.run = initialSnapshot;

  while (isCurrent(runId, generation)) {
    state.connection = state.lastEventSequence === 0 ? "connected" : "reconnecting";
    try {
      await api.events(
        runId,
        state.lastEventSequence,
        (event) => {
          if (isCurrent(runId, generation)) observe(runId, event);
        },
        controller.signal,
      );
    } catch (error) {
      if (controller.signal.aborted || !isCurrent(runId, generation)) return;
      if (!(error instanceof EventGapError)) {
        if (globalThis.navigator?.onLine === false) {
          state.connection = "offline";
          await waitForOnline(controller.signal);
          if (!isCurrent(runId, generation)) return;
        } else {
          state.connection = "reconnecting";
          await delay(800, controller.signal);
        }
      }
    }
    if (!isCurrent(runId, generation)) return;
    const refreshedSnapshot = await api.run(runId, controller.signal);
    if (!applySnapshot(runId, generation, refreshedSnapshot)) return;
    if (terminalStatuses.has(state.run.status)) {
      if (loadAudit && ["completed", "completed_with_warnings"].includes(state.run.status)) {
        const audit = await loadAudit(runId, controller.signal);
        if (!isCurrent(runId, generation)) return;
        state.audit = audit;
      }
      state.connection = "offline";
      return;
    }
    state.connection = "reconnecting";
  }
}

export async function cancelRun(runId: string): Promise<void> {
  if (state.run?.id !== runId || !["queued", "running"].includes(state.run.status)) return;
  const generation = recoveryGeneration;
  state.cancelPending = true;
  state.error = "";
  try {
    const cancelled = await api.cancel(runId, recoveryController?.signal);
    applySnapshot(runId, generation, cancelled);
  } finally {
    if (isCurrent(runId, generation)) state.cancelPending = false;
  }
}

export function stopRunRecovery(): void {
  recoveryGeneration += 1;
  recoveryController?.abort();
  recoveryController = null;
  state.connection = "offline";
  state.cancelPending = false;
}

export const runState = state;
