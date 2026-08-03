# Third-party notices / 第三方声明

PaperSeek is distributed under the Apache License 2.0. This page lists the third-party packages used by PaperSeek and the external data source integrated for computer-science conference search.

PaperSeek 使用 Apache License 2.0 发布。本页列出 PaperSeek 使用的第三方软件包，以及计算机顶会检索所接入的外部数据源。

## Runtime dependencies / 运行依赖

| Project | License | PaperSeek usage |
| --- | --- | --- |
| [Pydantic](https://github.com/pydantic/pydantic) | [MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE) | Typed configuration, search plans, checkpoints, and search-state contracts. |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | [MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE) | Optional `paperseek[harness]` support for bounded structured-output retries. |
| [LangChain Core](https://github.com/langchain-ai/langchain) | [MIT](https://github.com/langchain-ai/langchain/blob/master/LICENSE) | Runnable interface used by the optional graph backend. |
| [LangGraph](https://github.com/langchain-ai/langgraph) | [MIT](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) | Optional explicit state-graph execution backend. |

These packages are installed as separate Python distributions and retain their own license and copyright notices.

上述项目作为独立 Python 包安装，并保留各自的许可证和版权声明。

## PaperHub integration / PaperHub 集成

[Yupu-Wang/paper-hub](https://github.com/Yupu-Wang/paper-hub) provides the manifest and content-addressed shards used by the computer-science top-conference source. PaperSeek integrates this source with the author's permission and reads the published index at runtime.

[Yupu-Wang/paper-hub](https://github.com/Yupu-Wang/paper-hub) 为计算机顶会数据源提供 manifest 和内容哈希 shard。PaperSeek 经作者同意集成该数据源，并在运行时读取公开索引。
