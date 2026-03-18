# AlignHub Backend

AlignHub 后端基于 **FastAPI + SQLAlchemy + AgentScope**，提供：

- Provider / Model 管理
- Agent / Tool / Skill / MCP 管理
- Chat Session / Run 编排
- WebSocket 实时事件流
- Feishu 集成

## 启动

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

可用地址：

- API Base: `http://127.0.0.1:8000/api/v1`
- Health: `http://127.0.0.1:8000/healthz`

## 关键模块

- `app/runtime.py`：运行编排与 RunManager
- `app/tools.py`：内置工具
- `app/feishu.py`：Feishu 门面
- `app/services/runtime_models.py`：模型运行时适配
- `app/services/mcp_runtime.py`：MCP 运行时
- `app/services/workspace.py`：运行工作区复制与清理
- `app/services/feishu_*.py`：Feishu 细分服务

## Demo

```bash
curl -X POST http://127.0.0.1:8000/api/v1/demo/bootstrap
```

## 说明

- 默认数据库：SQLite
- 默认会在 Run 结束后清理运行工作区
- Feishu 事件目前仅支持明文模式

详细说明请查看仓库根目录 `README.md`。
