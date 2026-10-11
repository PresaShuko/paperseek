# 第一次检索

在本地启动 PaperSeek，连接模型，把一个研究问题变成阅读清单。

希望直接使用？打开 [PaperSeek 在线版](https://paperseek.app/)，阅读[在线版指南](../online/index.md)。

## 1. 安装

需要 **Python 3.12 或更新版本**，建议使用独立环境。

::: code-group
~~~bash [macOS / Linux]
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "paperseek==1.0.0b1"
~~~
~~~powershell [Windows PowerShell]
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "paperseek==1.0.0b1"
~~~
:::

从 1.0.0-beta1 源码安装时，改为 `python -m pip install ./backend`。修改前端源码后，请按[贡献指南](../contributing.md)重新构建界面。

## 2. 启动

~~~bash
paperseek serve
~~~

打开 **[http://127.0.0.1:8765](http://127.0.0.1:8765)**，使用期间保持终端运行。

安装包已包含前端页面，仅运行应用不需要 Node.js。

## 3. 连接模型

打开侧栏底部**设置 → 模型 API**，点击**添加连接**。选择 **LLM**、服务商和模型，填写 Key；自定义服务还需要确认基础地址与协议。可先点击**测试连接**检查模型草稿，再点击**保存**。在**默认使用**的**检索与评分**中选择已保存的连接，然后通过侧栏的**文献检索**返回。

OpenAI Chat Completions、OpenAI Responses 和 Anthropic Messages 是不同协议，不能只根据模型名称判断接口格式。

模型草稿的测试不会保存连接，数据源测试则有不同的保存行为，见下文。服务端默认值的设置见[配置参考](../reference/configuration.md)。

## 4. 输入问题

> 开源软件如何获得支持长期维护的资金？

如有 OpenAlex Key，打开**设置 → 数据源 → OpenAlex → 配置**，填写后点击**保存**。此数据源弹窗中的**测试连接**也会先保存当前密钥和选项，再执行测试；测试失败或随后取消弹窗，都不会撤销保存。

通过侧栏返回**文献检索**，选择 **OpenAlex**，只有必要时才在**更多选项**中限制研究领域。第一次使用可保留 **Auto**，也可以根据问题范围主动选择检索预算。

点击**开始检索**，或按 **Ctrl+Enter / ⌘+Enter**，在流程区查看检索与排序进展。

## 5. 阅读结果

打开**结果**，查看摘要与相关性理由，导出 CSV 或 JSON。社区版将历史保存在本地。

通过侧栏的**检索历史**重新打开记录，或点击标题旁的**全部**进入完整列表。有引用数据时查看**引用证据**，也可以选文献开始[实验性综述](reviews.md)。从侧栏进入[文献计量](bibliometrics.md)，可分析完整的实际获取候选集。

## 遇到问题时

先查看[常见问题](../reference/troubleshooting.md)。本地配置也可通过命令检查：

~~~bash
paperseek doctor --json
~~~

配置检查成功不代表上游在整个长任务中始终有余额或保持可用。
