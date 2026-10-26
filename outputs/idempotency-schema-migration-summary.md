
### 修复幂等表旧数据库列名不一致（2026-10-26）

- 用户提供的 traceback 已确认 500 根因：`sqlite3.OperationalError: no such column: agent_run_keys.key_hash`，发生在 `AgentRunService.reserve()` 查询映射时。数据库表之前按旧模型创建，列名为 `key`；代码已改为 `key_hash`。此外旧表缺少当前模型要求的 `created_at`。
- 原因：SQLAlchemy `Base.metadata.create_all()` 只建缺失表，不会修改已存在表的列；模型变更后需要显式数据库迁移。
- backend/app/storage/database.py：新增 `migrate_legacy_agent_run_keys(engine)`。检测旧 schema 后，在同一 SQLite 事务将 `key` 重命名为 `key_hash`，用 SHA-256 哈希已存原始 key，并补充 `created_at`（历史行使用固定 epoch 时间默认值）。当前 schema 下重复调用是 no-op；不删除表、不清数据。
- backend/app/main.py：应用启动 `create_all()` 后调用该迁移，因此普通重启或 reload 启动会自动兼容已有 SQLite 文件。
- backend/tests/test_storage_migrations.py：创建包含旧 `key` 列和一条历史幂等映射的 legacy DB，运行迁移，验证 key 被哈希、列结构补齐、原运行仍可用相同原始 key 重放。
- 验证：F:\DevSupportAgent/backend 全量113 passed，git diff --check通过。线上/用户实际模型没有被请求。
- 实际数据库只读检查确认迁移前 columns 是 session_id/key/fingerprint/run_id，行数0；代码 reload 后 columns 为 session_id/key_hash/fingerprint/run_id/created_at，行数仍0；8000 /health 返回200。因表原先没有数据，升级没有改动旧请求记录。
- 用户后续操作：同一个幂等 key 若曾映射失败/旧运行，会按原设计重放旧记录；要重试新 Agent run 请换新的 Idempotency-Key。8000 已 reload，真实 POST 联调由用户执行；如果仍有问题看新的 traceback。
