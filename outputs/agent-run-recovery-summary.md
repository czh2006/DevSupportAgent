# Agent 运行中断检测与惰性恢复

日期：2026-10-26

## 目标

服务进程异常退出后，避免运行记录永久停留在 `running`。系统在用户读取详情、事件或重放相同幂等请求时检查运行年龄；超过 3 分钟后标为 `interrupted`。

## 改动

- `backend/app/services/agent_run_service.py`：使用原子条件更新将过期运行改为 `interrupted`，设置 `RUN_INTERRUPTED` 和结束时间，并在同一事务写入中断事件。不会推测执行耗时，也不会自动重跑 Agent。
- `backend/app/schemas/agent_run.py`：运行响应状态增加 `interrupted`。
- `backend/app/agent/events.py`：事件类型增加 `run_interrupted`。
- `backend/app/api/agent_runs.py`：读取运行事件前先触发同一过期检查。
- `backend/tests/test_agent_run_recovery.py`：覆盖详情查询和事件查询的恢复、近期运行保护、事件幂等、过期运行重放不重复调用 Agent。

## 并发与失败语义

更新条件要求状态仍为 `running` 且创建时间不晚于截止时间。只有一个并发请求能成功更新并写入 `run_interrupted`，状态和事件一起提交。相同幂等键只返回中断记录；如需重试，由调用者使用新的幂等键发起新运行。

该机制是惰性检查，不是后台定时任务。没有详情、事件或幂等重放请求时，过期记录仍会留在数据库中。它不提供断点续跑或工具补偿。

## 验证

- `python -m pytest tests -q -p no:cacheprovider`：117 passed。
- `git diff --check`：通过。
- 未启动真实 API/MCP，没有请求 DeepSeek，没有修改 `.env`。
- 不涉及数据库列变更，不需要迁移。
