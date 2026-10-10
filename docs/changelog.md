---
outline: 2
---

# Changelog

Features, improvements, and upgrade notes, from the first demo to PaperSeek 1.0.0-beta.

## 1.0.0-beta {#v1-0-0-beta}

PaperSeek 1.0.0-beta is a **complete architectural refactor with breaking changes**. It rebuilds the execution model, frontend, storage boundaries, and distribution around a shared research application, with an explicit migration path for existing user data.

### Three modules and independent histories

- Top-level Search, Bibliometrics, and Review tabs, a collapsible module history sidebar, and a bottom account menu and standalone settings pages in the shadcn visual style.
- Preliminary bibliometrics over the actually retrieved deduplicated candidate corpus; native-field coverage, keyword co-occurrence, bounded bibliographic coupling, cached networks, and independent exports. LLM scoring remains a subset.
- Review citation evidence alongside papers, outline, and draft; new reviews preserve available source graph snapshots.
- Rename records without changing original queries or execution settings.

This beta follows 0.2.x directly. Python packages use the normalized version `1.0.0b1`; the public release and container tag are `1.0.0-beta`. The documentation describes this target release; deployment status is reported separately.

### Architecture rebuilt around clear responsibilities

- Separate `paperseek_core` for retrieval, query iteration, citation expansion, ranking, and source/model protocols; `paperseek_app` for run submission, execution, persistence, and queries; and deployment adapters for Community and Hosted.
- Use one application layer across Web, CLI, HTTP API, and MCP. The search core is independent of FastAPI, authentication, SQLite, and Supabase.
- Replace cross-repository copies with a pinned Community wheel. Hosted consumes the shared Python implementation and Vue sources from the same artifact, adding its own account, storage, and service policies.
- Rebuild the frontend with Vue 3, TypeScript, and Vite. Shared research pages use the versioned `/api/v1` contract; generated API types keep frontend and backend interfaces aligned.
- Use explicit asynchronous workflows and httpx clients, with Pydantic models at the boundaries. Retire the experimental harness and obsolete runtime entry points.

### Persistent tasks, cancellation, and recovery

- Make saved searches database-backed runs with worker leases, ordered events, checkpoints, and result artifacts. Community can resume compatible interrupted work from committed checkpoints.
- Restore saved pages from a run snapshot and replayed events, then follow updates through SSE. Reconnecting the browser does not submit a new search.
- Coordinate cancellation and lease ownership so an obsolete worker or a late provider response cannot commit results after cancellation.
- Separate source/model failures from persistence failures: optional retrieval or ranking stages can report warnings and fall back, while a failed result commit cannot be presented as success.
- Introduce versioned SQLite migrations through Alembic and explicit migration commands. Community uses SQLite and local files; Hosted uses its own PostgreSQL and Storage adapters. Anonymous online BYOK remains temporary and does not create saved research history.

Community supports a single local service with an embedded worker, or an explicitly separate worker. Hosted runs its API and worker on the server and serves the Vue frontend separately. Recovery follows each edition’s policy; browser reconnection is distinct from restarting an interrupted server task.

### A complete research workspace

- Vue 3 interface with English and Chinese, consistent navigation, and task-stage progress.
- Question-driven query iteration, bounded retrieval, relevance ranking, and transparent search history.
- Eight scholarly source integrations, with source-specific fields and access settings.
- Local fusion, Embedding + Rerank, and System One preliminary-ranking options.
- Citation expansion and an interactive citation map through OpenAlex.
- Saved runs, filtering, selection, and complete CSV/JSON exports.
- **Experimental** abstract-based reviews with editable outlines, section writing, versions, citations, and Markdown/Word/BibTeX exports.

### One application, several entry points

The Web UI, six-command CLI, versioned HTTP API, and independent same-version MCP adapter reuse the same application services. Community keeps data in local SQLite and files. The online product adds accounts, service models, queueing, and isolated storage.

### Upgrade notes

Python **3.12+** is required. Old Python imports, internal APIs, frontend endpoints, and retired CLI/configuration entries are not retained. Supported 0.2 data and environment settings have explicit migration commands; migrated configuration uses the new names without a legacy runtime fallback. See the [migration guide](self-hosting/upgrade.md) and [architecture notes](contributing.md#architecture).

Search uses abstracts and metadata provided by the source. Standalone cross-source abstract and citation-count enrichment are no longer part of the configuration.

## 0.2.1 {#v0-2-1}

July 5, 2026 · Provider routing and hosted service updates

### Models and retrieval

- Expanded provider routing with NVIDIA NIM and OpenRouter support.
- Updated PaperHub query handling and candidate-pool narrowing.

### Reliability

- Corrected NVIDIA reranker endpoint handling and improved ranking fallbacks.
- Added retries for transient API failures.
- Unified shared LLM route logging across providers.

### Documentation

- Expanded PaperSeek Service documentation, including hosted data-source credentials and release notes.

[Original release notes](https://github.com/MingfengHong/paperseek/releases/tag/v0.2.1)

## 0.2.0 {#v0-2-0}

July 4, 2026 · More sources and multi-lane retrieval

### Search and ranking

- Expanded the source lineup with arXiv, Semantic Scholar, PubMed, computer-science conferences, and Crossref.
- Introduced source-specific queries, intent recognition, and feedback across query iterations.
- Added preliminary ranking before LLM scoring. Retrieval combines relevance, influence or citations, freshness, and local quality signals, using RRF, BM25/term coverage, and local hashing embeddings.
- Added optional OpenAI-compatible embedding and reranker services.

### Online accounts

- Updated email registration and sign-in, with GitHub and ModelScope OAuth.
- Introduced a daily allowance of 20 successful searches for signed-in users at that release.

[Original release notes](https://github.com/MingfengHong/paperseek/releases/tag/v0.2.0)

## 0.1.1 {#v0-1-1}

June 6, 2026 · Discipline filters and bilingual use

### Search filters

- Added source-specific disciplines using OpenAlex Fields and Web of Science Categories.
- Applied OpenAlex discipline filters to both initial retrieval and citation expansion.
- Fixed handling of OpenAlex Field labels containing commas across the CLI, environment settings, API, and interface selections.

### Interface and packaging

- Added Chinese/English switching and refreshed user and deployment documentation.
- Reorganized the community package around its self-contained core.
- Included Docker/runtime packaging fixes, history improvements, and provider updates.

[Original release notes](https://github.com/MingfengHong/paperseek/releases/tag/v0.1.1)

## 0.1.0 {#v0-1-0}

June 2, 2026 · First demo release

The first release established the literature-discovery workflow:

- Research questions in Chinese or English, LLM-generated queries, and iterative widening or narrowing based on source results.
- Metadata collection and LLM relevance scores with brief explanations.
- OpenAlex citation expansion and an interactive map with dragging, zooming, and panning.
- Web results with search, filters, selection, and CSV export.
- Local Web UI, command-line use, Docker deployment, and an optional Agent Skill.
- Support for hosted model providers, compatible endpoints, and local Ollama.

The demo release linked to its commit history without a separate feature list. This summary follows the [README at the 0.1.0 tag](https://github.com/MingfengHong/paperseek/blob/v0.1.0/README.md).

[Original release](https://github.com/MingfengHong/paperseek/releases/tag/v0.1.0) · [Code history](https://github.com/MingfengHong/paperseek/commits/v0.1.0/)
