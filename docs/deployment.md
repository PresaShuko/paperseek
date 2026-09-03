# PaperSeek Community 部署指南

本文档对应 v0.3.0 Community 单机产品。Hosted、Supabase 和服务器 worker 不属于本仓库的 Community 部署拓扑。

## 1. 本地 wheel

```bash
python -m pip install "paperseek==0.3.0"
export PAPERSEEK_LLM_API_KEY=your-key
paperseek serve --host 127.0.0.1 --port 8765
```

健康检查：

```text
GET /health
GET /ready
```

默认 SQLite 是 `~/.paperseek/paperseek.db`。生产式本地部署应显式指定可备份的数据目录：

```bash
paperseek serve --database /srv/paperseek/paperseek.db
```

## 2. 分进程模式

默认 `serve` 已带一个 embedded executor。只有明确需要单机 API/worker 分进程时才使用：

```bash
paperseek serve --database /srv/paperseek/paperseek.db --no-worker
paperseek worker --database /srv/paperseek/paperseek.db
```

两者必须使用同一个 SQLite 文件和 artifact 目录。不要同时让默认 embedded executor 与独立 worker 无意竞争同一部署。

## 3. Docker Compose

```bash
docker compose up -d
docker compose logs -f
docker compose down
```

正式 Compose 只有一个 Community 服务：

- 镜像：`ghcr.io/mingfenghong/paperseek`
- 数据卷：`paperseek-data`
- 容器用户：非 root
- 健康检查：`/health`
- 数据目录：`/var/lib/paperseek`

停止并重新创建容器后，named volume 中的 SQLite、历史、结果和 artifacts 必须继续存在。最终镜像不包含 Node、npm cache 或编译工具。

## 4. 环境变量

复制 `.env.example` 并只填写需要的项。当前部署名称如下：

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `PAPERSEEK_DATABASE` | `/var/lib/paperseek/paperseek.db` | 可选 SQLite 路径。 |
| `PAPERSEEK_LLM_API_TYPE` | `openai_responses` | LLM 协议。 |
| `PAPERSEEK_LLM_MODEL` | `gpt-5.4-mini` | 模型名。 |
| `PAPERSEEK_LLM_BASE_URL` | `https://api.openai.com/v1` | 模型 base URL。 |
| `PAPERSEEK_LLM_API_KEY` | `your-key` | LLM API key。 |
| `PAPERSEEK_OPENALEX_API_KEY` | `your-key` | 可选但推荐。 |
| `PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY` | `your-key` | 可选。 |
| `PAPERSEEK_PUBMED_API_KEY` | `your-key` | 可选。 |
| `PAPERSEEK_WOS_API_KEY` | `your-key` | WoS 必需。 |
| `PAPERSEEK_WOS_DB` | `WOS` | WoS database selector。 |
| `PAPERSEEK_GOOGLE_SCHOLAR_API_KEY` | `your-key` | Serper API key。 |

运行时只读取这些新名称。旧 `.env` 必须先单向转换：

```bash
paperseek migrate \
  --legacy-env /path/to/old.env \
  --output-env /path/to/paperseek-v0.3.env
```

迁移输出不回显密钥、不会覆盖冲突目标，并拒绝语义已变化的旧选项。不要把旧名称重新加入容器环境。

## 5. 反向代理

Community 默认绑定 loopback。需要局域网或公网访问时：

1. 让反向代理终止 TLS。
2. 只开放反向代理端口。
3. 配置访问控制、请求体上限和合理超时。
4. 不把 SQLite、artifact 或 `.env` 目录暴露为静态文件。
5. 保持 `/api/v1/*`、health、artifact/export 路由由 FastAPI 处理；SPA fallback 只处理 Vue 深链。

## 6. ModelScope Studio

ModelScope Studio 如需部署 PaperSeek，应直接运行同一 Community 镜像/正式 `paperseek serve`。没有 ModelScope-only runtime、专属配置分支或 fallback。

ModelScope API-Inference 仍可以像其它 OpenAI-compatible 模型服务一样作为本次运行的 LLM/embedding 路由；这不改变 Community 部署形态。部署默认值仍使用 `PAPERSEEK_LLM_*` 名称，用户也可以在 Web 当前会话中提供 route/key。

## 7. MCP 容器

独立 MCP 镜像不加入 Community 默认 Compose。它作为 Streamable HTTP 服务非 loopback 绑定时必须：

- 显式 `0.0.0.0`；
- 配置 Bearer service token；
- 配置 Host/Origin allowlist；
- 由反向代理提供 TLS；
- 保持请求体、并发与速率边界。

本地 CLI 默认仍绑定 `127.0.0.1`。详见 `integrations/mcp/README.md`。

## 8. 迁移、备份与恢复

v0.2 SQLite 通过正式命令迁移：

```bash
paperseek migrate --from-v0.2 /path/to/old.db
```

迁移前会创建一致性备份。部署升级前还应备份当前 SQLite 与 artifact 目录；恢复时两者必须保持同一时间点。

## 9. 交付核验

部署后至少核对：

1. `/health` 与 `/ready`。
2. `/api/v1/sources` 返回八个数据源。
3. `/runs/{id}`、results、citation-map 与 history 深链返回 Vue index。
4. `/api/v1/*` 不被 SPA fallback 截获。
5. 一次受控检索、Stop 和历史读取。
6. 容器/进程重启后 SQLite、结果和 artifacts 仍可读。
7. 日志、run snapshot 和导出中没有凭据。

## 10. 安全

- `.env` 权限应限制到部署用户；不要提交真实值。
- 对外服务必须使用 TLS 和访问控制。
- 定期备份 SQLite/artifacts，并在升级前演练恢复。
- 不把生产内部地址、用户问题或完整 provider 错误正文复制到公开日志。
