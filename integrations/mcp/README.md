# PaperSeek MCP

`paperseek-mcp` is the independent Model Context Protocol integration for PaperSeek. It contains no search, provider, ranking, or persistence implementation; it calls the application services supplied by the exact same-version `paperseek` distribution.

<!-- mcp-name: io.github.MingfengHong/paperseek -->

Install the matched release:

```text
pip install paperseek-mcp==0.3.0
```

The default local transport is stdio:

```text
paperseek-mcp --transport stdio
```

Loopback HTTP transports are explicit:

```text
paperseek-mcp --transport streamable-http --host 127.0.0.1 --port 8766 --path /mcp
paperseek-mcp --transport sse-legacy --host 127.0.0.1 --port 8766
```

The legacy SSE transport exists only for clients that have not migrated to Streamable HTTP. A transport session is never the search-run lifetime: `start_search` returns a durable `run_id`, and later status, event, result, citation, cancel, and export calls use that ID.

The local database defaults to `~/.paperseek/paperseek.db`. Override it with `--database` or `PAPERSEEK_DATABASE`.
