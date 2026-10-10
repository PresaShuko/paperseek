# Maintaining the research workspace

The Community package is the source of shared Python and Vue implementation. Hosted consumes a pinned wheel containing both; deployment adapters must not copy algorithms or pages.

Shared UI tokens, layout rules, and stylesheet ownership are documented in the [design system maintenance guide](./design-system.md).

| Responsibility | Location |
| --- | --- |
| Compact native metadata and document identity | `paperseek_core/bibliometrics/corpus.py` |
| Distributions and coverage | `paperseek_core/bibliometrics/statistics.py` |
| Bounded sparse networks | `paperseek_core/bibliometrics/networks.py` |
| Create/read/export/delete analysis use cases | `paperseek_app/bibliometrics/services.py` |
| Storage contract and small record models | `paperseek_app/bibliometrics/ports.py`, `models.py` |
| Community persistence and HTTP composition | `paperseek_community/persistence/sqlite_bibliometrics.py`, `api_routes/bibliometrics.py` |
| Navigation, menus, module history | `web/src/features/workspace/` |
| Analysis views, controls, browser layout worker | `web/src/features/bibliometrics/` |
| Search draft and reusable model inputs | `web/src/features/search/search-draft.ts`, `SearchModelSettings.vue` |
| Review evidence and saved source graph | `web/src/features/review/ReviewEvidence.vue` |

Retrieval keeps metadata for already-returned pages before lane/fusion selection. The ranking inputs retain their existing bounds. A completed run writes a separate `bibliometric_corpus` artifact; result APIs and event streams do not carry the corpus. Community recovery checkpoints preserve it. Hosted's policy can skip checkpoints while still retaining the final corpus artifact.

Creating an analysis copies a compact corpus and overview into independent compressed files. SQL stores summaries, descriptors, and bounded network-cache references. Detail requests read the overview only; network computation and corpus export load the corpus on demand. Deletion first marks the record, then deletes files, then retains a minimal idempotency tombstone so late retries cannot recreate it. Adapters enforce ownership before any file descriptor is exposed to a use case.

Network limits are explicit in the core. API concurrency guards bound simultaneous expensive operations; the browser computes only layout in a worker. Large source payloads, abstracts, full result records, and model credentials are not duplicated into the compact corpus. Do not move heavy analysis into history listing or page-mount effects.

Saved searches and reviews have display titles separate from their question/topic and execution versions. Module history shares UI behavior, while each API keeps its own persistence rules. User keys stay in an in-memory draft; account changes must reset that draft and remount owner-scoped history. Restoring a past run never silently changes it to current service defaults.

Run `bibliometrics_contract.py`, the retrieval-boundary/recovery contracts, import-boundary checks, frontend type checks, and the offline `workspace_flow.spec.ts` and `review_flow.spec.ts` fixtures after relevant changes. The opt-in `backend/scripts/benchmark_bibliometrics.py` records synthetic 3,000/10,000-paper costs; it is not a remote server or browser latency benchmark.

## Workspace surfaces

`WorkspaceShell.vue` owns the sidebar, icon rail, mobile drawer and the one main scroll surface. `WorkspacePreferences.vue` is a routed settings page; `SettingsNavigation.vue` and `SourceSettings.vue` own category navigation and source options. Search model controls and their in-memory draft remain in the search feature. Global defaults do not replace a saved review's own model controls. `styles/features/workspace-shell.css`, `settings.css`, and `styles/dialog.css` own their respective surfaces; generic dialogs no longer depend on review styles. Hosted supplies menu identity, services and a stable application-level account dialog through the shell slot; it does not copy the shell.
