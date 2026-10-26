# Agent 运行取消与客户端断开语义

日期：2026-10-26

## 行为约定

- 客户端断开连接不等于取消任务。Agent 执行通过 `asyncio.shield` 与 HTTP 等待隔离；执行会继续，持久化结果，用户重连后查询详情。
- 用户显式取消调用 `POST /sessions/{session_id}/agent-runs/cancel`，并发送原 `Idempotency-Key`。创建运行的 POST 同步等待结果，运行期间客户端还不知道 `run_id`，所以取消按幂等键定位运行。也保留了按 run_id 取消的接口。状态先从 `running` 改为 `cancel_requested` 并马上返回；Agent 在安全检查点停止后变成 `cancelled`。
- 已经发出的模型或 MCP 请求不能被这个协作式取消接口强行撤回。等待该请求结束或超时，再停止后续步骤。

## 代码变化

- `backend/app/services/agent_run_service.py`：增加按运行 ID 或幂等键定位的取消请求、取消状态查询和终态处理。取消请求状态和 `run_cancel_requested` 事件一起提交；结束时 `cancel_requested` 优先于迟到的 Agent 结果。过期恢复也接管停滞的 `cancel_requested` 记录。
- `backend/app/api/agent_runs.py`：加入取消接口；Agent 通过 shield 任务运行，HTTP 等待被取消时继续等 Agent 完成并保存结果。
- `backend/app/agent/runner.py`：增加异步 `should_cancel` 回调，在模型和工具步骤边界检查；发现取消后抛 `AgentRunCancelled`。
- `backend/app/services/agent_event_service.py`：允许请求取消后为正在收尾的阶段写入完成事件。
- `backend/app/schemas/agent_run.py` 和 `backend/app/agent/events.py`：声明新增状态和事件。
- `backend/tests/test_agent_run_cancellation.py`：覆盖取消状态流转、重复取消、同幂等键不重复执行、工具尚未启动前取消以及跨会话访问拒绝。

## 幂等与工具边界

相同 `Idempotency-Key` 重放会返回原来的 cancel_requested/cancelled 运行，不会创建第二个 Agent。当前 MCP 工具只读，所以取消后已开始的日志查询可以安全地完成。将来增加有副作用的工具时，应使用下游支持的工具级幂等键（例如 run_id 与 tool_call_id 的组合），并保留审计记录；HTTP 运行幂等本身不能保证外部写操作 exactly-once。

## 验证与联调

- `python -m pytest tests -q -p no:cacheprovider`：121 passed。
- `git diff --check`：通过。
- 本轮未启动真实服务或请求 DeepSeek，不需要数据库迁移。
- 手动联调：运行 Agent 时，在第二个浏览器标签页向 `/sessions/{session_id}/agent-runs/cancel` 发送相同 `Idempotency-Key`；先观察 `cancel_requested`，随后查询到 `cancelled`。事件应有 `run_cancel_requested` 和 `run_cancelled`。原幂等键重放返回同一运行。若 Agent 已先完成，取消返回终态是正常竞态。关闭浏览器等待不会触发取消。

由于运行中的客户端还没有响应里的 `run_id`，取消 API 同时支持使用客户端在请求开始时已知的 `Idempotency-Key` 查找运行。没有使用幂等键创建的运行只能在已经获知 `run_id` 后按 ID 取消。
