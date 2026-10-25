# DevSupport Agent

开发者故障排查与工单协作平台。

## 当前进度

- 创建 FastAPI 后端
- 提供健康检查接口
- 使用 SQLite 持久化排障会话
- 支持创建和查询排障会话
- 校验请求参数，查询不存在的会话返回 404
- 支持添加和分页查询会话消息
- 消息按会话隔离，重启后仍然保留
- 用户消息角色由后端指定

## 启动后端

在项目根目录激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

然后启动服务：

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

健康检查：http://127.0.0.1:8000/health

接口文档：http://127.0.0.1:8000/docs

## 运行测试

进入后端目录后执行：

```powershell
python -m pytest -v
```

测试使用独立的内存 SQLite 数据库，不会修改本地运行数据。