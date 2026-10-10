# Contributing

PaperSeek welcomes documentation fixes, source-adapter improvements, reproducible bug reports, and focused product changes. Start with a small issue or discuss a substantial behavior change before implementation.

## Repository map

| Location | Responsibility |
| --- | --- |
| `backend/src/paperseek_core` | Retrieval, source clients, ranking, and model protocols |
| `backend/src/paperseek_app` | Application use cases and persistence ports |
| `backend/src/paperseek_community` | SQLite, local artifacts, HTTP server, and CLI |
| `web` | Shared Vue 3 + TypeScript product UI |
| `integrations/mcp` | Independent MCP adapter |
| `integrations/skills` | Agent usage instructions |
| `docs` | Public English/Chinese docs, including online usage |

Hosted consumes a pinned Community distribution. Fix shared behavior here instead of maintaining a second copy in Hosted.

## Architecture {#architecture}

Version 1.0.0-beta completes an architectural refactor into a modular monolith with persistent task execution. Research logic, application operations, and deployment-specific adapters have separate responsibilities, while shipping as a usable local application.

### Dependency boundaries

The research core implements query iteration, retrieval, candidate selection, citations, ranking, and source/model protocols. It can use Pydantic and httpx, but does not depend on web routing, account identity, or a database. Application services own run submission, cancellation, execution, and queries; storage is accessed through explicit ports. Community and Hosted supply the concrete storage, credential, network, and deployment policies.

The `paperseek` distribution contains `paperseek_core`, `paperseek_app`, and `paperseek_community`, plus the built Web UI. The core and application layer do not have separate package releases. `paperseek-mcp` is an independently installable, version-matched protocol adapter that calls the same application services.

### Run lifecycle

For a saved search, submission records the effective configuration and creates a run. A worker claims it with a lease, executes the asynchronous workflow, and commits events, checkpoints, and artifact references through application transactions. Final results become visible as a completed run only after the required data has been committed.

The frontend loads the run snapshot and follows sequenced events over SSE. Community recovery uses compatible committed checkpoints, so completed steps or batches can be reused. Cancellation and lease checks prevent outdated execution from committing late results. A checkpoint from an incompatible workflow is rejected rather than interpreted as current state.

Community stores these records in SQLite, with Alembic-managed migrations and local artifact files. Hosted provides PostgreSQL and Storage adapters, account isolation, and its own task-recovery policy. Anonymous online BYOK keeps research content in memory and does not create a durable research run. Keep these differences in the adapters and application policies, outside the search algorithm.

### Shared frontend and releases

Vue 3 + TypeScript pages consume `/api/v1`; the OpenAPI generation script produces API types and model presets. Change the backend contract and regenerate its frontend representation together.

Hosted consumes a pinned Community wheel with a verified source identity and checksum. It extracts the shared Vue sources from that same wheel and adds account and service UI. A shared change takes effect there when the pinned artifact is rebuilt and updated, not merely when a neighboring checkout is edited.

For the changes introduced by this release, see the [1.0.0-beta changelog](changelog.md#v1-0-0-beta). For existing local installations, follow the [upgrade guide](self-hosting/upgrade.md). The [workspace maintenance guide](reference/bibliometrics-architecture.md) maps the new modules to their source responsibilities and verification points.

## Development setup

Use Python 3.12+, uv, and the Node/npm versions declared in `web/package.json`.

```sh
uv sync --locked --project backend
npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web run build -- --outDir ../backend/src/paperseek_community/static --emptyOutDir
uv run --locked --project backend paperseek serve
```

For frontend iteration, run `npm --prefix web run dev` while the backend is available. Check `web/vite.config.ts` for the development proxy.

## Checks

```sh
uv run --directory backend --locked ruff check --config pyproject.toml src ../integrations/mcp/src
uv run --directory backend --locked python tests/import_boundaries.py
uv run --directory backend --locked python -m unittest discover -s tests/contract -p "*contract.py"
uv run --directory backend --locked python scripts/generate_openapi_types.py --check
npm --prefix web run typecheck
npm --prefix web run build
```

Run checks appropriate to the changed behavior and consult CI for the complete release checks. Keep provider-backed experiments separate from deterministic tests. Never use a production database for migration or integration tests.

## Work on the docs

```sh
npm ci
npm run docs:dev
npm run docs:build
```

English pages live at `docs/`; Chinese equivalents at `docs/zh/`. Keep the information architecture aligned and update both languages when behavior changes. Site configuration and theme are in `docs/.vitepress/`.

Public guides should explain stable product behavior. Production keys, host-specific checklists, test transcripts, and one-off release records do not belong in public docs. Keep generated output outside source control; local builds may use `DOCS_OUT_DIR` and `DOCS_CACHE_DIR`.

## Publish the documentation

The documentation workflow builds pull requests and publishes pushes to
`main` into the generated `gh-pages` branch. Edit source pages rather than that
generated branch. Keep `docs/public/CNAME` set to `docs.paperseek.app`; the
custom subdomain uses a DNS-only CNAME to `mingfenghong.github.io`. GitHub Pages
serves the site over HTTPS. A local build verifies the site, but does not publish it.

## Submit a change

Explain the problem, resulting behavior, affected surfaces, and validation. Include before/after screenshots for visible UI changes. Add behavior tests where needed; avoid tests tied only to a temporary file arrangement.

Follow the [Code of Conduct](https://github.com/MingfengHong/paperseek/blob/main/CODE_OF_CONDUCT.md), preserve attribution, and keep contributions compatible with [Apache-2.0](https://github.com/MingfengHong/paperseek/blob/main/LICENSE).
