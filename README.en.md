<div align="center">
  <img src="docs/assets/paperseek_logo_with_text.png" alt="PaperSeek" width="520">
  <p>Stoppable, recoverable, and auditable academic literature search.</p>
</div>

# PaperSeek Community

PaperSeek v0.3.0 turns a research question into a structured search plan, runs multi-lane retrieval, citation expansion, abstract enrichment, and ranking across eight scholarly sources, and persists runs, events, checkpoints, results, and artifacts in local SQLite storage.

This is a breaking architecture release. The supported product is the Vue + FastAPI + application/core path; removed Python internals, commands, configuration values, and runtimes do not have compatibility fallbacks.

## Features

- OpenAlex, arXiv, Crossref, Semantic Scholar, PubMed, Google Scholar through Serper, PaperHub top CS conferences, and Web of Science Starter.
- Query planning, iterative query control, Query Portfolio, multi-lane retrieval, local hashing/BM25/RRF, and optional external embedding/reranking.
- OpenAlex citation expansion and citation maps.
- DOI abstract enrichment through an independent Crossref service for every selected source; optional Crossref candidate-metadata enrichment is off by default.
- Durable runs, events, checkpoints, leases, cancellation, recovery, history, results, exports, and artifacts.
- Run-scoped bilingual Web UI, formal CLI, independent `paperseek-mcp` distribution, and Community Docker image.

## Install

Python 3.12 or newer is required.

```bash
python -m pip install "paperseek==0.3.0"
export PAPERSEEK_LLM_API_KEY=your-key
paperseek serve
```

Open `http://127.0.0.1:8765`.

The only Python project directory for a source checkout is `backend/`:

```bash
python -m pip install ./backend
paperseek version
```

## Formal CLI

The installed `paperseek` exposes six commands:

```text
paperseek serve
paperseek worker
paperseek search
paperseek doctor
paperseek migrate
paperseek version
```

Run a durable search:

```bash
paperseek search "responsible AI governance in public services" \
  --source openalex \
  --search-budget medium \
  --citation-enabled \
  --output json
```

CLI and HTTP submissions share the submission normalizer, responsibility-focused application services, SQLite unit of work, artifact store, and executor. For an explicit split-process deployment:

```bash
paperseek serve --database /data/paperseek.db --no-worker
paperseek worker --database /data/paperseek.db
```

## Configuration

`.env.example` lists the current runtime variables:

| Variable | Purpose |
| --- | --- |
| `PAPERSEEK_DATABASE` | Optional SQLite path. |
| `PAPERSEEK_LLM_API_TYPE` | `openai_chat`, `openai_responses`, or `anthropic_messages`. |
| `PAPERSEEK_LLM_BASE_URL` | Model API base URL. |
| `PAPERSEEK_LLM_MODEL` | Model name. |
| `PAPERSEEK_LLM_API_KEY` | LLM API key. |
| `PAPERSEEK_OPENALEX_API_KEY` | Optional OpenAlex key. |
| `PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY` | Optional Semantic Scholar key. |
| `PAPERSEEK_PUBMED_API_KEY` | Optional PubMed key. |
| `PAPERSEEK_GOOGLE_SCHOLAR_API_KEY` | Serper API key. |
| `PAPERSEEK_WOS_API_KEY` | Required for WoS. |
| `PAPERSEEK_WOS_DB` | WoS database selector; defaults to `WOS`. |

Runtime settings do not read old variable names. Convert a v0.2 env file once:

```bash
paperseek migrate --legacy-env /path/to/old.env --output-env /path/to/paperseek-v0.3.env
```

Only legacy names with unchanged meaning are migrated. Other source keys are listed by name in `ignored_settings` and ignored. Secrets are never echoed, conflicting targets are not overwritten, and an unknown target key, target conflict, or invalid input file stops the migration.

## Web, API, and storage

The main routes are `/search`, `/runs/{run_id}`, `/runs/{run_id}/results`, `/runs/{run_id}/citation-map`, and `/history`. Refresh recovery uses the snapshot, durable event replay, and `Last-Event-ID` SSE reconnection.

The formal API is under `/api/v1`; OpenAPI is available at `/openapi.json`. Community SQLite defaults to `~/.paperseek/paperseek.db`, with artifacts in the same data directory.

## MCP and Skill

MCP is a separate, exactly matched distribution:

```bash
python -m pip install "paperseek==0.3.0" "paperseek-mcp==0.3.0"
paperseek-mcp --transport stdio
```

The repository Skill is a thin guide to the installed CLI/API/MCP. It does not contain a second search runtime and never asks users to paste secrets into chat.

## Docker

```bash
docker compose up -d
```

The Community Compose file has one service using `ghcr.io/mingfenghong/paperseek` and the `paperseek-data` named volume. Health endpoints are `/health` and `/ready`.

## Documentation

- [User manual](docs/user-manual.md)
- [Deployment guide](docs/deployment.md)
- [v0.3.0 notes](docs/v0.3.0.md)
- [Independent MCP integration](integrations/mcp/README.md)

## Security boundary

- Do not store API keys in the repository, logs, history, or artifacts.
- The local service binds to loopback by default; public deployments need a secured reverse proxy.
- PaperSeek returns metadata and links, not paywall bypass or bulk PDF downloads.

## License

Apache License 2.0. External APIs and data remain subject to their own terms.
