# Models and ranking

Use a language model for search planning and relevance assessment. Optional preliminary ranking helps choose the candidates for final model scoring.

## Connect a model

In Community, or online with your own key, choose a provider and model, then verify the key, base URL, and protocol. Presets are starting values; the provider must offer that model.

| Protocol | Operation |
| --- | --- |
| OpenAI Chat Completions | `/chat/completions` |
| OpenAI Responses | `/responses` |
| Anthropic Messages | `/v1/messages` |

Use the base URL expected by the protocol, without duplicating the operation path. Chat Completions compatibility does not imply Responses compatibility.

PaperSeek Service provides a model dropdown. Its operator manages endpoint and key configuration.

## Preliminary ranking

**Local fusion is the default.**

| Mode | Behavior | Extra service |
| --- | --- | --- |
| Local fusion | Combines local lexical/hashed semantic signals and retrieval ranks | None |
| Embedding + Rerank | External embedding and reranking before final selection | Embedding and reranking APIs |
| Decision model | Scores locally fused candidates with the System One protocol | Compatible decision API |

Local fusion refers only to preliminary ranking. The complete search still uses a language model and network requests.

The decision route assesses up to twice the final LLM candidate budget before choosing the final subset. Available candidates and budget limits still apply.

## Settings by edition

**Community / your own key:** configure model routes and credentials. The writing model can differ from the search model.

**PaperSeek Service:** choose allowed search and writing models. Preliminary-ranking choices remain visible, while endpoints and secrets stay on the server.

## Local models

Community can connect to a compatible model reachable from the machine running PaperSeek, including loopback.

Online, connections saved with your own key cannot point to loopback, private, link-local, or other unsafe destinations, which protects the server against SSRF. `127.0.0.1` would address the online server, not your laptop. Use Community for local endpoints.

## Fallbacks and failures

An optional ranking failure can preserve local ordering with a warning; it does not mean external ranking succeeded. Check the recorded run configuration and execution status.

Authentication, credit, rate-limit, timeout, and invalid-response errors require different remedies. See [troubleshooting](../reference/troubleshooting.md).
