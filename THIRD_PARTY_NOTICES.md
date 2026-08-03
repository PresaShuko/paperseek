# Third-party notices / 第三方声明

PaperSeek is distributed under the Apache License 2.0. This page records the open-source dependencies and projects that directly informed the product.

PaperSeek 使用 Apache License 2.0 发布。本页记录项目使用的开源依赖和直接提供设计启发的项目。

## Runtime dependencies / 运行依赖

| Project | License | PaperSeek usage |
| --- | --- | --- |
| [Pydantic](https://github.com/pydantic/pydantic) | [MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE) | Typed configuration, search plans, checkpoints, and search-state contracts. |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | [MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE) | Optional `paperseek[harness]` support for bounded structured-output retries. |
| [LangChain Core](https://github.com/langchain-ai/langchain) | [MIT](https://github.com/langchain-ai/langchain/blob/master/LICENSE) | Runnable interface used by the optional graph backend. |
| [LangGraph](https://github.com/langchain-ai/langgraph) | [MIT](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) | Optional explicit state-graph execution backend. |

These packages are installed as separate Python distributions and retain their own license and copyright notices.

上述项目作为独立 Python 包安装，并保留各自的许可证和版权声明。

## Acknowledged references / 参考项目致谢

- [dr-dumpling/paper-search-cli](https://github.com/dr-dumpling/paper-search-cli): CLI interaction and literature-search workflow organization.
- [666ghj/MiroFish](https://github.com/666ghj/MiroFish): split-pane layout and visible workflow presentation.
- [clarivate/wosstarter_python_client](https://github.com/clarivate/wosstarter_python_client): WoS Starter endpoint behavior and response schema. PaperSeek uses its own lightweight adapter.
- [Lloyd-Jahn/openclaw-paper-search](https://github.com/Lloyd-Jahn/openclaw-paper-search): organization of paper-search tooling.
- [bytedance/pasa](https://github.com/bytedance/pasa): Crawler/Selector responsibility separation, candidate queues, and planned citation traversal.
- [wanshuiyin/Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep): explicit state, budgets, checkpoints, and recovery for long-running workflows.

## PaperHub integration / PaperHub 集成

[Yupu-Wang/paper-hub](https://github.com/Yupu-Wang/paper-hub) provides the manifest and content-addressed shards used by the computer-science top-conference source. PaperSeek integrates this source with the author's permission, implements its own query/provider layer, and reads the published index at runtime.

[Yupu-Wang/paper-hub](https://github.com/Yupu-Wang/paper-hub) 为计算机顶会数据源提供 manifest 和内容哈希 shard。PaperSeek 经作者同意集成该数据源，自行实现查询和 provider 层，并在运行时读取公开索引。
