<div align="center">
  <img src="docs/assets/paperseek_logo_with_text.png" alt="PaperSeek" width="520">
  <p>可停止、可恢复、可审计的学术论文检索工具。</p>
</div>

# PaperSeek Community

PaperSeek v0.3.0 把研究问题转换为结构化检索计划，在八个学术数据源上执行多路召回、引用扩展、摘要补全和排序，并将运行、事件、检查点、结果和 artifacts 持久化到本地 SQLite/文件系统。

v0.3.0 是 breaking architecture release。正式产品只有新的 Vue + FastAPI + application/core 路径；旧 Python 内部 API、旧命令、旧运行时和已移除配置值不提供兼容 fallback。

## 主要能力

- 八数据源：OpenAlex、arXiv、Crossref、Semantic Scholar、PubMed、Google Scholar/Serper、PaperHub 计算机顶会、Web of Science Starter。
- Query planning、检索式迭代和 Query Portfolio。
- 多路召回、本地 hashing/BM25/RRF，以及可选外部 embedding/reranker。
- OpenAlex 引用扩展与引用图谱。
- 任意 selected source 的 DOI 通过独立 Crossref 服务补全摘要；可选 Crossref candidate metadata 补全默认关闭。
- LLM 排序失败时保留本地顺序并记录降级事实。
- durable run/events/checkpoint/lease/cancel/recovery。
- Web、CLI、历史、结果、导出、图谱与中英文界面。
- 独立 `paperseek-mcp` 发行和 Community Docker 镜像。

## 快速开始

需要 Python 3.12+。

```bash
python -m pip install "paperseek==0.3.0"
export PAPERSEEK_LLM_API_KEY=your-key
paperseek serve
```

打开 `http://127.0.0.1:8765`。

从源码安装时，Python distribution 的项目目录是 `backend/`：

```bash
python -m pip install ./backend
paperseek version
```

## 正式 CLI

安装后的 `paperseek` 只提供六个主命令：

```text
paperseek serve
paperseek worker
paperseek search
paperseek doctor
paperseek migrate
paperseek version
```

运行一次持久检索：

```bash
paperseek search "responsible AI governance in public services" \
  --source openalex \
  --search-budget medium \
  --citation-enabled \
  --output json
```

CLI 与 Web API 共用 submission normalizer、按职责拆分的 application services、SQLite UoW、artifact store 和 executor。缺少 key 或 provider 失败会留下明确的失败/降级运行，不会切到 fixture 或第二条 pipeline。

高级单机分进程部署：

```bash
paperseek serve --database /data/paperseek.db --no-worker
paperseek worker --database /data/paperseek.db
```

WoS database selector 与 WoS Category 独立：

```bash
paperseek search "graph learning" \
  --source wos \
  --wos-db WOS \
  --field-id "Computer Science, Artificial Intelligence"
```

## 配置

`.env.example` 只列当前运行时支持的新名称：

| 变量 | 用途 |
| --- | --- |
| `PAPERSEEK_DATABASE` | 可选 SQLite 路径。 |
| `PAPERSEEK_LLM_API_TYPE` | `openai_chat`、`openai_responses` 或 `anthropic_messages`。 |
| `PAPERSEEK_LLM_BASE_URL` | 模型 API base URL。 |
| `PAPERSEEK_LLM_MODEL` | 模型名。 |
| `PAPERSEEK_LLM_API_KEY` | LLM API key。 |
| `PAPERSEEK_OPENALEX_API_KEY` | OpenAlex，可选但推荐。 |
| `PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar，可选。 |
| `PAPERSEEK_PUBMED_API_KEY` | PubMed，可选。 |
| `PAPERSEEK_WOS_API_KEY` | WoS 必需。 |
| `PAPERSEEK_WOS_DB` | WoS database，默认 `WOS`。 |
| `PAPERSEEK_GOOGLE_SCHOLAR_API_KEY` | Serper API key。 |

模型路由、embedding、reranker、数据源筛选、预算、引用和 enrichment 是每次运行的受校验选项，不是内部环境开关。

### 一次性迁移旧 `.env`

运行时不会双读旧变量。使用迁移边界生成新的 `.env`：

```bash
paperseek migrate \
  --legacy-env /path/to/old.env \
  --output-env /path/to/paperseek-v0.3.env
```

只有仍具有相同语义的常用名称会映射。源文件中的其它键只按名称列入 `ignored_settings` 并忽略；迁移不会回显密钥、不会覆盖冲突目标，重复运行返回 `already_migrated`。目标文件含未知键、目标冲突或输入文件无效时，迁移会拒绝继续。`paperseek doctor --json` 只按变量名报告当前进程中可迁移的旧配置。

### 迁移 v0.2 SQLite

```bash
paperseek migrate --from-v0.2 /path/to/paperseek-v0.2.db
```

迁移前建立一致性备份，并支持可测试的重复执行语义。详见[用户手册](docs/user-manual.md)。

## Web UI

![PaperSeek web interface](docs/assets/paperseek-web.png)

主导航始终包含 Search、Results、Citation Map 和 History。运行使用可恢复 URL：

```text
/search
/runs/{run_id}
/runs/{run_id}/results
/runs/{run_id}/citation-map
/history
```

刷新时按 snapshot → 持久事件回放 → Last-Event-ID SSE 重连恢复。Stop 使用 `running → cancelling → cancelled`，迟到响应不能复活运行或写入结果。

## 数据源

| 数据源 | Key | 说明 |
| --- | --- | --- |
| OpenAlex | 推荐 | 多路召回、语义通道、引用扩展与图谱。 |
| arXiv | 不需要 | 原生 category、摘要和 PDF。 |
| Crossref | 不需要 | DOI/出版元数据及跨源补全。 |
| Semantic Scholar | 可选 | 学术图谱、引用数和开放 PDF 线索。 |
| PubMed | 可选 | 生物医学与生命科学。 |
| Google Scholar | 必需 | 通过 Serper 请求。 |
| 计算机顶会 | 不需要 | PaperHub 顶会数据。 |
| Web of Science Starter | 必需 | WoS database 与 Category。 |

`GET /api/v1/sources` 是 capability 的正式机器契约。原生筛选、文本提示、引用扩展等字段由选定 source 的能力校验。

## API 与持久化

正式 API 前缀是 `/api/v1`，OpenAPI 位于 `/openapi.json`。主要动作包括 run 提交/读取/取消、事件、结果、图谱、审计、artifact、导出、历史和删除。

Community 默认 SQLite 位于 `~/.paperseek/paperseek.db`，artifact 位于同一数据目录。浏览器 session key 保存在加密 transient credential store，终态后删除，不进入历史、事件、URL、checkpoint 或 artifact。

## MCP

MCP 是独立且同版本的发行：

```bash
python -m pip install "paperseek==0.3.0" "paperseek-mcp==0.3.0"
paperseek-mcp --transport stdio
```

stdio、Streamable HTTP 和标记为 legacy 的 SSE transport 共享一套九工具 registry。非 loopback HTTP 必须配置服务 token、Host/Origin allowlist；TLS 交给反向代理。详见 [`integrations/mcp/README.md`](integrations/mcp/README.md)。

## Agent Skill

仓库中的 [`skills/paperseek/SKILL.md`](skills/paperseek/SKILL.md) 是薄路由说明：它调用已安装的正式 CLI/API/MCP，不复制检索 pipeline，不要求用户在对话中粘贴密钥。

## Docker

```bash
docker compose up -d
```

正式 Community Compose 是单服务，使用 `ghcr.io/mingfenghong/paperseek` 与 `paperseek-data` named volume。健康检查为 `/health` 和 `/ready`。部署细节见[部署指南](docs/deployment.md)。

## 文档

- [完整用户手册](docs/user-manual.md)
- [部署指南](docs/deployment.md)
- [v0.3.0 说明](docs/v0.3.0.md)
- [独立 MCP](integrations/mcp/README.md)

## 安全边界

- 不在仓库、日志、历史或 artifacts 中存储 API key。
- 默认服务只绑定 loopback；公开部署应使用反向代理和访问控制。
- 不自动下载付费全文；链接和元数据仍受来源网站条款约束。
- 发布前以最终 wheel、浏览器、MCP、Docker 与持久化门禁为准，不用 fixture-only smoke 冒充产品验证。

## License

Apache License 2.0。第三方数据与 API 仍遵循各自条款。
