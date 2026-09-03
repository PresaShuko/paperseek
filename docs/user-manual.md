# PaperSeek 用户手册

本文档对应 PaperSeek Community v0.3.0 的正式安装产品。命令、环境变量和 API 以安装后的 `paperseek --help`、`/openapi.json` 与本页为准。

## 1. 安装与启动

需要 Python 3.12 或更高版本。

```bash
python -m pip install "paperseek==0.3.0"
paperseek version
```

从源码工作区安装时，Python distribution 的唯一项目目录是 `backend/`：

```bash
python -m pip install ./backend
paperseek version
```

最小部署配置使用新的 `PAPERSEEK_*` 名称：

```bash
export PAPERSEEK_LLM_API_KEY=your-key
paperseek serve
```

默认地址是 `http://127.0.0.1:8765`。数据库默认位于 `~/.paperseek/paperseek.db`，也可以通过 `--database` 或 `PAPERSEEK_DATABASE` 指定。

## 2. 正式 CLI

v0.3.0 只提供六个主命令：

```text
paperseek serve
paperseek worker
paperseek search
paperseek doctor
paperseek migrate
paperseek version
```

查看当前安装的精确参数：

```bash
paperseek --help
paperseek search --help
paperseek migrate --help
```

### 2.1 检索

```bash
paperseek search "responsible AI governance in public services" \
  --source openalex \
  --search-budget medium \
  --citation-enabled \
  --output json
```

`search` 与 Web API 共用 submission normalizer、按职责拆分的 application services、SQLite、artifact store 和 executor。输出包含 run ID、终态、warning 和结果；缺少凭据或 provider 失败会留下可审计运行，不会切换到 fixture 或另一条 pipeline。

常用选项：

| 选项 | 说明 |
| --- | --- |
| `--source` | 八个数据源之一。 |
| `--search-budget` | `fast`、`medium`、`high` 或 `max`。 |
| `--field-id` | 可重复的数据源原生筛选值。 |
| `--field-hint` | 仅用于支持文本提示的数据源。 |
| `--citation-enabled` | 对支持的数据源启用引用扩展。 |
| `--retrieval-crossref-enrichment` | 通过 DOI 补齐缺失的年份和引用数，默认关闭。 |
| `--wos-db` | WoS database selector，默认 `WOS`。 |
| `--llm-provider` / `--llm-api-type` / `--llm-model` / `--llm-base-url` | 本次运行的模型路由。 |

WoS database 与 WoS Category 是不同字段：

```bash
paperseek search "graph learning" \
  --source wos \
  --wos-db WOS \
  --field-id "Computer Science, Artificial Intelligence"
```

### 2.2 服务与 worker

`serve` 默认启动 API、随 wheel 发布的 Vue 应用和一个嵌入式 executor：

```bash
paperseek serve --host 127.0.0.1 --port 8765
```

需要明确的单机分进程部署时，共享同一 SQLite 文件：

```bash
paperseek serve --database /data/paperseek.db --no-worker
paperseek worker --database /data/paperseek.db
```

不要在默认 embedded executor 已运行时再无意启动第二个 worker。`worker --once` 最多领取一个排队运行后退出。

### 2.3 Doctor

```bash
paperseek doctor --source openalex --json
paperseek doctor --source wos --wos-db WOS --json
```

doctor 检查 Python、目录、SQLite、数据源、WoS database、LLM、embedding 和 reranker 配置。默认不要求外网 live 成功。它只按变量名报告当前进程中可映射的旧配置并提示执行一次性迁移，不会回显值；未知或已废弃变量不会触发专门诊断。

### 2.4 数据与配置迁移

迁移 v0.2 SQLite：

```bash
paperseek migrate --from-v0.2 /path/to/paperseek-v0.2.db
```

默认在源库旁建立一致性备份并原地升级；也可以显式指定新目标和备份：

```bash
paperseek migrate \
  --from-v0.2 /path/to/old.db \
  --database /path/to/new.db \
  --backup /path/to/old.backup.db
```

一次性迁移旧 `.env` 名称：

```bash
paperseek migrate \
  --legacy-env /path/to/old.env \
  --output-env /path/to/paperseek-v0.3.env
```

迁移命令不会覆盖冲突的目标值，不回显密钥，重复执行返回 `already_migrated`。只有仍具有相同语义的常用名称会映射；源文件中的其它键只按名称列入 `ignored_settings` 并忽略。目标文件含未知键、目标冲突或输入文件无效时，迁移会拒绝继续。

## 3. 部署环境变量

`.env.example` 是当前完整清单：

| 变量 | 默认/用途 |
| --- | --- |
| `PAPERSEEK_DATABASE` | 可选；Community SQLite 文件。 |
| `PAPERSEEK_LLM_API_TYPE` | 默认 `openai_responses`。 |
| `PAPERSEEK_LLM_BASE_URL` | 默认 OpenAI API base URL。 |
| `PAPERSEEK_LLM_MODEL` | 默认 `gpt-5.4-mini`。 |
| `PAPERSEEK_LLM_API_KEY` | LLM API key。 |
| `PAPERSEEK_OPENALEX_API_KEY` | OpenAlex，可选但推荐。 |
| `PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar，可选。 |
| `PAPERSEEK_PUBMED_API_KEY` | PubMed，可选。 |
| `PAPERSEEK_WOS_API_KEY` | WoS 必需。 |
| `PAPERSEEK_WOS_DB` | WoS database，默认 `WOS`。 |
| `PAPERSEEK_GOOGLE_SCHOLAR_API_KEY` | Serper API key。 |

不要把 API key 写入仓库、日志、run snapshot、checkpoint 或 artifact。

模型、embedding、reranker、数据源筛选、预算、引用和 enrichment 是每次运行的受校验选项，不是需要永久写进部署环境的内部旋钮。

## 4. 数据源

`GET /api/v1/sources` 返回当前八个数据源、凭据要求和筛选/引用能力：

| 数据源 | 凭据 | 主要能力 |
| --- | --- | --- |
| OpenAlex | 推荐 | 多路召回、语义通道、引用扩展和图谱。 |
| arXiv | 不需要 | 预印本、原生 category、摘要和 PDF 链接。 |
| Crossref | 不需要 | DOI 与出版元数据；也是跨源摘要/元数据补全服务。 |
| Semantic Scholar | 可选 | 学术图谱、引用数和开放 PDF 线索。 |
| PubMed | 可选 | 医学与生命科学文献。 |
| Google Scholar | 必需 | 通过 Serper 获取 Scholar 结果。 |
| 计算机顶会 | 不需要 | PaperHub 顶会数据。 |
| Web of Science Starter | 必需 | WoS Starter database 与 Category。 |

筛选字段必须按 source capability 使用。原生筛选、文本提示和不支持筛选是三种不同模式；跨源字段组合会被 submission 校验拒绝。

## 5. Web UI

主导航始终包含：

- Search：提交、配置检查、Stop 和四阶段运行审计。
- Results：搜索、筛选、排序、选择、详情和导出。
- Citation Map：缩放、平移、拖动、节点选择与图例。
- History：重新打开流程、结果、图谱，导出或删除历史。

运行 URL 是可恢复的：

```text
/search
/runs/{run_id}
/runs/{run_id}/results
/runs/{run_id}/citation-map
/history
```

刷新时客户端先读取 snapshot 和持久事件，再携带最后 sequence 重连 SSE。浏览器临时凭据仅保存在加密的 transient credential store，终态后删除；不会出现在历史、事件、URL 或导出中。

## 6. 结果、历史和导出

正式 API 前缀是 `/api/v1`。常用资源：

```text
POST /api/v1/runs
POST /api/v1/runs/{run_id}/cancel
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/events
GET  /api/v1/runs/{run_id}/results
GET  /api/v1/runs/{run_id}/citation-map
GET  /api/v1/runs/{run_id}/audit
GET  /api/v1/runs/{run_id}/artifacts
GET  /api/v1/history
DELETE /api/v1/history/{run_id}
```

JSON/CSV、引用图和审计 artifacts 由运行状态管理。活动运行不能被删除；终态删除会同时清理数据库记录和文件，并对失败清理保留可重试事实。

## 7. MCP 与 Agent Skill

MCP 是独立发行：

```bash
python -m pip install "paperseek==0.3.0" "paperseek-mcp==0.3.0"
paperseek-mcp --transport stdio
```

它复用同一组 application services 和 Community composition，通过 SQLite、artifact store 与 executor 暴露九个 durable tools：start、status、events、results、citation graph、cancel、export、sources 和 capabilities。Streamable HTTP 的非 loopback 绑定必须配置 Bearer token、Host/Origin allowlist，并由反向代理承担 TLS。

仓库中的 Agent Skill 是薄路由说明，只调用已安装的正式 CLI/API/MCP，不携带第二套检索 runtime，也不要求用户把 key 粘贴到对话中。

## 8. Docker

```bash
docker compose up -d
```

正式 Community Compose 是单服务，镜像使用 `ghcr.io/mingfenghong/paperseek`，数据保存在 `paperseek-data` named volume。健康检查：

```text
GET /health
GET /ready
```

容器重启后 SQLite、历史、结果和 artifacts 应继续存在。

## 9. 故障排查

推荐顺序：

1. `paperseek version`
2. `paperseek doctor --source SOURCE --json`
3. 检查数据库目录可写性与凭据变量名。
4. 通过 Web 系统日志或 `/api/v1/runs/{id}/events` 查看稳定错误码。
5. 对旧配置先运行 `paperseek migrate --legacy-env ... --output-env ...`，不要把旧名称重新加回运行时。

常见情况：

- 缺少 LLM key：正式搜索会失败并留下可审计运行；配置 key 或选择本地无鉴权端点。
- 外部 embedding/reranker 失败：保持本地预排序/RRF，记录降级 warning。
- DOI 摘要或 metadata 服务失败：主运行继续并记录部分补全 warning。
- Stop：状态按 `running → cancelling → cancelled` 推进，迟到响应不能提交结果。
- SSE 断线：页面按持久 sequence 回放并重连，不需要重新发起检索。

## 10. 安全与隐私

- Community 默认只绑定 loopback；公开部署必须使用反向代理和适当访问控制。
- 不把 API key、完整 provider 错误正文或用户问题写入公开 issue/日志。
- 浏览器 session key、MCP token 和生产地址不得进入仓库。
- PaperSeek 不自动获取付费全文；结果中的链接仍受来源网站条款和版权约束。
- 更新前备份 SQLite 和 artifacts；v0.2 数据必须通过正式迁移命令升级。

## 11. 版本边界

v0.3.0 是 breaking architecture release：不保证旧 Python 内部 import、内部类函数、旧前端接口、已废弃命令或已移除配置值。兼容只存在于一次性 SQLite/环境配置迁移边界；正式运行只使用新 schema、新环境变量与新 application services。
