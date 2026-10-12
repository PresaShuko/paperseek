# HTTP API

社区版在 `/api/v1` 下提供版本化 HTTP API。已安装服务的 `/openapi.json` 是完整字段与响应结构的依据。

## 提交任务

本地服务已配置好模型后：

```sh
curl -X POST http://127.0.0.1:8765/api/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: example-search-001" \
  -d '{"question":"How does open-source funding affect maintenance?","source":"openalex","search_budget":"fast"}'
```

接口以 HTTP **202** 返回任务快照，请保留其中的任务 ID。每次有意新建任务使用新的幂等键；仅在重试同一次提交时复用原键。

## 跟踪与读取任务

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/runs/{run_id}` | 当前快照 |
| GET | `/api/v1/runs/{run_id}/events` | SSE 进度事件 |
| POST | `/api/v1/runs/{run_id}/cancel` | 请求取消 |
| GET | `/api/v1/runs/{run_id}/results` | 分页结果 |
| GET | `/api/v1/runs/{run_id}/citation-map` | 引用图谱 |
| GET | `/api/v1/runs/{run_id}/export?format=csv` | 完整导出 |
| GET | `/api/v1/history` | 历史任务 |

OpenAPI 还描述了选中文献导出、产物、审计数据、历史删除和综述项目及任务接口。

SSE 用于传输进度。断开时先获取任务快照，再恢复事件连接，不要仅为了恢复进度重复提交检索。取消是一个请求，正在执行的上游调用可能不会立即终止。

## 实现客户端

- 保存任务 ID 与事件序号，支持恢复。
- 跟随响应分页，不假设一次读取全部结果。
- 明确处理排队、执行、取消中和终态。
- 显示安全错误码及可读信息，不暴露密钥或上游原始响应。
- 将论文内容与生成文本视为数据，不作为可执行标记。

在线版共用检索契约，但另有认证、归属校验、服务模式与积分限制。匿名 BYOK 流程不能替代需要账户的持久化接口。集成时以对应部署的 schema 和认证流程为准。
