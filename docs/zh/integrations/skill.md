# Agent Skill

在支持 Skill、能够运行本地命令的 Agent 中使用 PaperSeek。Skill 指导 Agent 检查安装、配置环境、执行文献检索，并读取已保存的结果。

检索在本地社区版中执行，历史与产物保存在其本地存储中；模型和数据源请求使用你配置的服务。不需要 PaperSeek 账户。

## 添加 Skill

Skill 位于仓库的 [integrations/skills/paperseek](https://github.com/MingfengHong/paperseek/tree/main/integrations/skills/paperseek)。

1. 通过 Agent 的 Skill 安装功能添加该目录，或将完整的 `paperseek` 文件夹复制到客户端规定的项目级或用户级 Skill 目录。
2. 保持 `SKILL.md` 与 `references/` 目录在一起。参考文件包含安装步骤、受支持的命令和数据源选项。
3. 如客户端要求，重新加载 Skill，并确认它识别到名称 **paperseek**。

可以先添加 Skill，再安装社区版。复制 Skill 本身不会安装 Python、PaperSeek 或模型凭据。

## 首次使用

直接让 Agent 使用 PaperSeek 处理一个具体研究问题：

> 请使用 PaperSeek Skill 检索“开源软件融资如何影响软件维护”的相关文献。先检查本地安装；如果未安装，请在独立环境中安装并检查配置。使用 OpenAlex，保存检索记录，整理相关论文并附来源链接。

Skill 会指导 Agent：

1. **检查安装。** 定位 `paperseek` 并查看版本，优先复用已有环境或可执行文件路径。
2. **按需安装。** 使用 Python 3.12+ 与独立环境；有执行权限的 Agent 可以完成安装，否则提供步骤供你操作。
3. **检查配置。** 执行 `paperseek doctor --json`，不发起真实检索；先解决缺少的必要模型或数据源配置。
4. **本地检索。** 选择数据源，通过社区版 CLI 提交问题，并保留任务 ID、状态、警告与结果。

已有安装不会自动升级，数据也不会自动迁移。更换版本时请遵循[升级指南](../self-hosting/upgrade.md)。

## 配置模型与数据源

通过本地进程环境，或 Agent 客户端的私有环境配置，提供模型连接与数据源凭据。Skill 使用与社区版相同的 `PAPERSEEK_*` 设置，详见[配置参考](../reference/configuration.md)、[模型设置](../guide/models.md)和[数据源](../guide/sources.md)。

不要将真实 Key 放入对话、`SKILL.md` 或提交到仓库的客户端配置。缺少必要值时，Agent 应说明配置项名称，并指导你在本地填写。

CLI 读取自身的进程环境。仅在网页表单中填写的值，不会自动配置另一个 Agent 进程；CLI 也不会自动加载 `.env` 文件。

## 继续研究

可以让 Agent 检查已保存的任务、归纳警告、读取规范化文献元数据，或协助导出结果。需要交互式筛选、历史记录和引用图谱时，可打开使用同一数据库的本地网页。

例如：

> 打开刚才保存的 PaperSeek 检索任务，告诉我任务状态和使用的数据源，整理最相关的文献，并协助将结果导出为 CSV。

相关性评分用于辅助筛选。使用生成的综合结论前，请核对原始研究；该 Skill 不会自动阅读论文 PDF，也不代表完成了系统综述。

## Skill、MCP 与 HTTP API 如何选择

| 入口 | 适合的场景 |
| --- | --- |
| **Agent Skill** | Agent 可以运行本地命令，需要安装与使用 PaperSeek 的指导 |
| [MCP](mcp.md) | 助手通过结构化工具开始、查询、取消和导出检索任务 |
| [HTTP API](api.md) | 开发自己的应用，对接运行中的 PaperSeek 服务 |

通过 Skill 使用 CLI 不需要安装 MCP，也不需要先启动网页服务。适合时，它也可以指导 Agent 使用已有本地 API 或同版本 MCP 集成。底层命令见[CLI 指南](cli.md)。
