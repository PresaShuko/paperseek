# 参与贡献

欢迎修正文档、改进数据源适配器、提交可复现问题和聚焦的产品改动。可以先从小问题开始；影响较大的行为调整，建议先在 Issue 中讨论。

## 目录职责

| 位置 | 职责 |
| --- | --- |
| `backend/src/paperseek_core` | 召回、数据源、排序与模型协议 |
| `backend/src/paperseek_app` | 应用用例与持久化端口 |
| `backend/src/paperseek_community` | SQLite、本地产物、HTTP 服务与 CLI |
| `web` | 共用的 Vue 3 + TypeScript 产品界面 |
| `integrations/mcp` | 独立 MCP 适配器 |
| `integrations/skills` | Agent 使用说明 |
| `docs` | 中英文公共文档，包含在线版使用指南 |

在线版基于同一份社区版发行包，公共行为请在本仓库修复。

## 架构 {#architecture}

1.0.0-beta1 完成了向模块化单体与持久任务执行架构的重构。研究逻辑、应用操作和部署适配各自承担明确职责，并共同交付为可直接使用的本地应用。

### 依赖边界

检索核心实现查询迭代、召回、候选选择、引用扩展、排序与数据源／模型协议。它可以使用 Pydantic 和 httpx，但不依赖网页路由、账户身份或数据库。应用服务负责提交、取消、执行与查询，通过明确的端口访问存储。社区版与在线版各自提供具体的存储、凭据、网络和部署策略。

`paperseek` 发行包包含 `paperseek_core`、`paperseek_app`、`paperseek_community` 和已构建的网页；核心与应用层不单独发布。`paperseek-mcp` 是可独立安装、版本匹配的协议适配器，调用同一应用服务。

### 任务生命周期

保存的检索在提交时记录有效配置并创建任务。worker 领取任务及租约，执行异步工作流，通过应用事务提交事件、检查点与产物引用。所需数据提交成功后，任务才能以完成状态呈现最终结果。

前端读取任务快照，再通过 SSE 跟随有序事件。社区版使用兼容的已提交检查点恢复，复用已经完成的步骤或批次。取消与租约校验阻止失效执行提交迟到结果；不兼容的工作流检查点会被拒绝，不会按新结构猜测恢复。

社区版将这些记录保存在 SQLite 中，以 Alembic 管理迁移，文件产物保存在本地。在线版提供 PostgreSQL、Storage、账户隔离及自身的任务恢复策略。在线匿名 BYOK 的研究内容只保存在内存，不创建持久研究任务。这些差异属于适配层与应用策略，不应进入检索算法。

### 共享前端与发行

Vue 3 + TypeScript 页面通过 `/api/v1` 工作；OpenAPI 生成脚本同时产生 API 类型和模型预设。修改后端契约时，需要同步生成前端表示。

本次变化见 [1.0.0-beta1 更新日志](changelog.md#v1-0-0-beta)，已有本地安装请按[升级指南](self-hosting/upgrade.md)迁移。新模块的文件职责和验证入口见[工作区维护说明（英文）](../reference/bibliometrics-architecture.md)。

## 开发环境

使用 Python 3.12+、uv，以及 `web/package.json` 声明的 Node/npm 版本。

```sh
uv sync --locked --project backend
npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web run build -- --outDir ../backend/src/paperseek_community/static --emptyOutDir
uv run --locked --project backend paperseek serve
```

前端开发可在后端运行时执行 `npm --prefix web run dev`，开发代理配置见 `web/vite.config.ts`。

## 验证改动

```sh
uv run --directory backend --locked ruff check --config pyproject.toml src ../integrations/mcp/src
uv run --directory backend --locked python tests/import_boundaries.py
uv run --directory backend --locked python -m unittest discover -s tests/contract -p "*contract.py"
uv run --directory backend --locked python scripts/generate_openapi_types.py --check
npm --prefix web run typecheck
npm --prefix web run build
```

按实际改动选择检查，完整发行检查参考 CI。真实提供方实验与确定性测试分开，迁移和集成测试不能连接生产数据库。

## 修改文档站

```sh
npm ci
npm run docs:dev
npm run docs:build
```

英文页面位于 `docs/`，中文对应页面位于 `docs/zh/`。保持两种语言的信息结构一致，行为变化时同步更新。主题和站点配置位于 `docs/.vitepress/`。

公共指南介绍稳定产品行为。生产密钥、特定服务器清单、测试长日志和一次性发布记录不属于公共文档。产物不提交到源码；本地构建可通过 `DOCS_OUT_DIR` 和 `DOCS_CACHE_DIR` 指定外部目录。

Pull Request 会自动构建文档站检查错误，合并后网站自动更新。请只修改 `docs/` 下的源文件。

## 提交改动

说明具体问题、改动后的行为、受影响的界面与验证结果。界面修改请附前后截图，需要时补充行为测试，避免只检查临时文件布局。

请遵守[行为准则](https://github.com/MingfengHong/paperseek/blob/main/CODE_OF_CONDUCT.md)，保留署名，使贡献兼容 [Apache-2.0](https://github.com/MingfengHong/paperseek/blob/main/LICENSE) 许可。
