# Management Layer Reference

## Installation

Install the Community package from a release or from this repository's only active Python source:

```bash
python -m pip install -e ./backend
paperseek version
paperseek doctor --json
```

The Skill does not contain a standalone fallback runtime. If `paperseek` is unavailable, install it rather than running source files from `skills/`.

## Current configuration

Use only current `PAPERSEEK_*` environment names. Common deployment settings are:

- `PAPERSEEK_DATABASE`
- `PAPERSEEK_LLM_API_TYPE`, `PAPERSEEK_LLM_BASE_URL`, `PAPERSEEK_LLM_MODEL`, `PAPERSEEK_LLM_API_KEY`
- `PAPERSEEK_OPENALEX_API_KEY`, `PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY`, `PAPERSEEK_PUBMED_API_KEY`
- `PAPERSEEK_GOOGLE_SCHOLAR_API_KEY`, `PAPERSEEK_WOS_API_KEY`, `PAPERSEEK_WOS_DB`

Never copy secret values into chat, logs, Skill files, documentation, or tests. Doctor reports configuration status and setting names without echoing values.

For a v0.2 env file, perform the explicit one-time conversion:

```bash
paperseek migrate --legacy-env .env.v0.2 --output-env .env
```

Review the name-only report, then load the new file. Runtime settings do not permanently read old names.

## Local service

```bash
paperseek migrate --database paperseek.db
paperseek serve --database paperseek.db --host 127.0.0.1 --port 8765
```

Health endpoints are `/health` and `/ready`; product endpoints are under `/api/v1`. The Vue application uses run-scoped routes such as `/runs/{run_id}`, `/runs/{run_id}/results`, and `/runs/{run_id}/citation-map`.

Use `paperseek serve --no-worker` only when a separate `paperseek worker` process owns execution for the same database.

## Diagnostics

`paperseek doctor --json` is a static readiness check. A warning may mean an optional credential or recommended contact email is absent; a failure means required local configuration or storage is unusable. It does not treat live third-party network success as a default hard requirement.

For an agent tool client, install the exact matched `paperseek-mcp` release and use its durable run tools. The MCP distribution is not part of the Community default Compose service.
