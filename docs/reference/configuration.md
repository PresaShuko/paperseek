# Configuration reference

There are three configuration layers: deployment defaults, the search form, and the immutable settings saved with a run. Editing today's form does not change an existing run.

## Community environment variables

The repository's [.env.example](https://github.com/MingfengHong/paperseek/blob/main/.env.example) is the deployment template.

| Variable | Use |
| --- | --- |
| `PAPERSEEK_DATABASE` | Local SQLite path; defaults to `~/.paperseek/paperseek.db` |
| `PAPERSEEK_LLM_API_TYPE` | `openai_responses`, `openai_chat`, or `anthropic_messages` |
| `PAPERSEEK_LLM_BASE_URL` | Provider API base URL |
| `PAPERSEEK_LLM_MODEL` | A model ID supported by that provider |
| `PAPERSEEK_LLM_API_KEY` | Model credential |
| `PAPERSEEK_OPENALEX_API_KEY` | OpenAlex key or key pool |
| `PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY` | Optional Semantic Scholar key |
| `PAPERSEEK_PUBMED_API_KEY` | Optional NCBI key |
| `PAPERSEEK_WOS_API_KEY` | Web of Science Starter key |
| `PAPERSEEK_WOS_DB` | WoS collection, for example `WOS` |
| `PAPERSEEK_GOOGLE_SCHOLAR_API_KEY` | Serper key or key pool |
| `PAPERSEEK_CONTACT_EMAIL` | Contact email used by source clients that support it |

Direct CLI/server execution reads the process environment. Docker Compose loads the optional `.env` file. A copied template alone does not configure a directly launched Python process.

### Example on PowerShell

```powershell
$env:PAPERSEEK_LLM_API_TYPE = "openai_chat"
$env:PAPERSEEK_LLM_BASE_URL = "https://your-provider.example/v1"
$env:PAPERSEEK_LLM_MODEL = "your-model-id"
$env:PAPERSEEK_LLM_API_KEY = "<your-key>"
paperseek serve
```

Replace all placeholders. Prefer your operating system or service manager's private secret configuration for unattended use. The URL above is deliberately not a working provider endpoint.

### OpenAlex and Serper key pools

Separate keys with whitespace, commas, or semicolons in the corresponding variable or key field. PaperSeek rotates the starting key and distinguishes authentication failures from transient failures.

Do not repeat a key to simulate extra capacity. Each provider still enforces its own access policies.

## Per-search settings

The form contains the research question, source, fields, budget, model connection, preliminary ranking, and source-specific options. See [search](../guide/search.md), [data sources](../guide/sources.md), and [models](../guide/models.md).

Protocol and base URL must agree. A server that implements Chat Completions does not necessarily implement Responses or Anthropic Messages. The usual OpenAI-compatible base URL ends in `/v1`; do not append `/chat/completions` when the field asks for a base URL.

## Optional ranking services

Local fusion needs no external preliminary-ranking endpoint. Embedding + Rerank and System One require their corresponding connections when used in Community or with your own key online. Their keys and model IDs can differ from the main language model.

## Online configuration

PaperSeek Service provides model lists and server-managed connections. With your own key, public provider connections are allowed after server-side address validation. Deployment secrets, internal routes, and allowlists are operator settings, not end-user fields.

See the [online guide](../online/index.md).
