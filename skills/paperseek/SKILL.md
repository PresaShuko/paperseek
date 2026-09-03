---
name: paperseek
description: Route literature-search tasks through an installed PaperSeek v0.3.0 CLI, local Web/API service, or matched paperseek-mcp integration. Use for searches, diagnostics, durable run inspection, results, exports, and citation maps.
license: Apache-2.0
compatibility: Requires the PaperSeek Community package. MCP use additionally requires the exact same-version paperseek-mcp package.
---

# PaperSeek

Use only the installed PaperSeek product. This Skill is guidance, not a bundled or fallback search runtime.

## References

- Read `references/source-routing.md` to choose among the eight Community sources.
- Read `references/cli-contract.md` for the six formal CLI commands and durable-run behavior.
- Read `references/management-layer.md` for installation, diagnostics, migration, Web/API, and secret handling.
- If a reference conflicts with the installed command help or `/openapi.json`, trust the installed product and report the documentation drift.

## Default workflow

1. Run `paperseek doctor --json` without live network checks.
2. Choose a source. OpenAlex is the default for broad discovery.
3. Run a durable search with `paperseek search "QUESTION" --source openalex --output json`.
4. Report the run status, source, warnings, result count, and useful normalized paper metadata. Treat relevance scores as screening signals, not proof.
5. For interactive history, filtering, export, and citation maps, use `paperseek serve --database PATH` and the run-scoped Web routes.
6. For tool clients, use the matched independent `paperseek-mcp` distribution; do not invent a second blocking pipeline.

## Boundaries

- Do not ask users to paste secrets into chat or write them into Skill files, documentation, tests, or logs.
- Configure current `PAPERSEEK_*` variables locally. Convert a v0.2 env file once with `paperseek migrate --legacy-env OLD --output-env NEW`.
- PaperSeek returns metadata and links; it does not bypass paywalls or bulk-download PDFs.
- Never fabricate missing DOI, authors, abstracts, citation counts, or source results.
- Do not claim a systematic review is complete from a single PaperSeek run.
