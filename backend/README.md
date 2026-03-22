# AlignHub Backend

AlignHub 后端基于 **FastAPI + SQLAlchemy + LangGraph**，负责模型配置管理、Agent 编排、讨论运行、实时事件流、运行回放数据持久化、Feishu 集成与本地工作区治理。

---

## 1. 当前能力

### 1.1 配置与资产管理

- Provider / Model 的新增、编辑、删除、测试
- Agent 的 CRUD、复制、Tool / Skill / MCP 绑定同步
- Skill 的手工创建、zip 上传解析、元数据维护、落盘清理
- MCP 的手工创建、jar 上传生成 stdio 配置、连接测试、调用测试、启动预览

### 1.2 会话与运行

- Chat Session CRUD
- 显式校验会话中必须存在 Moderator
- 启动 / 暂停 / 恢复 / 停止 Run
- 用户补充输入注入
- 用户消息可标记 `mark_important=true` 进入长期关注点
- Run 事件时间线、Tool Log、最终报告持久化
- WebSocket 实时订阅运行事件
- Run 删除与 Replay 数据读取支持

### 1.3 Feishu 集成

- Host Bot 全局配置
- Agent 独立 Bot 配置
- 消息测试发送
- `chat_id` 诊断
- 群聊 / 话题回调接入
- 自动绑定与自动建会话
- 支持 `#start`、`#ask`、暂停 / 恢复 / 停止等命令

> 当前只支持 Feishu 明文事件模式，暂不支持 Encrypt Key。

---

## 2. API 路由概览

### 2.1 Provider / Model

- `GET /api/v1/providers`
- `POST /api/v1/providers`
- `PUT /api/v1/providers/{provider_id}`
- `DELETE /api/v1/providers/{provider_id}`
- `POST /api/v1/providers/{provider_id}/test`
- `GET /api/v1/models`
- `POST /api/v1/models`
- `PUT /api/v1/models/{model_id}`
- `DELETE /api/v1/models/{model_id}`
- `POST /api/v1/models/{model_id}/test`

### 2.2 Tool / Skill / MCP / Agent

- `GET /api/v1/tools`
- `GET /api/v1/skills`
- `POST /api/v1/skills`
- `POST /api/v1/skills/upload-zip`
- `PUT /api/v1/skills/{skill_id}`
- `DELETE /api/v1/skills/{skill_id}`
- `GET /api/v1/mcps`
- `POST /api/v1/mcps`
- `POST /api/v1/mcps/upload-jar`
- `PUT /api/v1/mcps/{mcp_id}`
- `DELETE /api/v1/mcps/{mcp_id}`
- `POST /api/v1/mcps/{mcp_id}/test`
- `POST /api/v1/mcps/{mcp_id}/call-test`
- `GET /api/v1/mcps/{mcp_id}/startup-preview`
- `GET /api/v1/agents`
- `POST /api/v1/agents`
- `GET /api/v1/agents/{agent_id}`
- `PUT /api/v1/agents/{agent_id}`
- `DELETE /api/v1/agents/{agent_id}`
- `GET /api/v1/agents/{agent_id}/feishu-bot`
- `PUT /api/v1/agents/{agent_id}/feishu-bot`
- `DELETE /api/v1/agents/{agent_id}/feishu-bot`

### 2.3 Chat Session / Run

- `GET /api/v1/chat-sessions`
- `POST /api/v1/chat-sessions`
- `GET /api/v1/chat-sessions/{session_id}`
- `PUT /api/v1/chat-sessions/{session_id}`
- `DELETE /api/v1/chat-sessions/{session_id}`
- `POST /api/v1/chat-sessions/{session_id}/runs`
- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `DELETE /api/v1/runs/{run_id}`
- `POST /api/v1/runs/{run_id}/pause`
- `POST /api/v1/runs/{run_id}/resume`
- `POST /api/v1/runs/{run_id}/stop`
- `POST /api/v1/runs/{run_id}/user-input`
- `GET /api/v1/runs/{run_id}/events`
- `GET /api/v1/runs/{run_id}/tool-logs`
- `GET /api/v1/runs/{run_id}/report`
- `WS /api/v1/ws/runs/{run_id}`

### 2.4 Feishu / Demo

- `GET /api/v1/integrations/feishu/config`
- `PUT /api/v1/integrations/feishu/config`
- `GET /api/v1/integrations/feishu/agent-bots`
- `POST /api/v1/integrations/feishu/test-send`
- `POST /api/v1/integrations/feishu/diagnose-chat`
- `POST /api/v1/integrations/feishu/events`
- `POST /api/v1/demo/bootstrap`

---

## 3. 核心模块

### 3.1 启动与 API 装配

- `app/main.py`
  - FastAPI 生命周期、日志、CORS、中枢服务初始化
- `app/api.py`
  - 路由总装配
- `run_server.py`
  - 本地启动入口

### 3.2 运行时核心

- `app/runtime_langgraph.py`
  - LangGraph 讨论图、RunManager、Checkpoint 恢复、工作区清理
- `app/runtime_common.py`
  - Run 控制状态、事件落库、实时事件广播
- `app/services/discussion_turn_service.py`
  - Agent 回合、Moderator 回合、报告生成
- `app/services/discussion_state.py`
  - 结构化状态维护、补丁提案、冲突归并、重点关注点管理
- `app/services/discussion_prompts.py`
  - Prompt 组装、上下文压缩、最终报告摘要
- `app/services/context_retrieval.py`
  - FTS / sqlite-vec / lexical 混合检索
- `app/services/run_lifecycle.py`
  - Run 生命周期调度
- `app/services/run_persistence.py`
  - Run 持久化读写
- `app/services/run_execution_notifier.py`
  - 运行事件通知分发

### 3.3 Feishu 相关

- `app/feishu.py`
  - Feishu 门面与运行联动
- `app/services/feishu_commands.py`
  - 命令解析
- `app/services/feishu_callbacks.py`
  - 回调校验与消息解析
- `app/services/feishu_autobind.py`
  - 自动绑定、参与 Agent 推断、诊断
- `app/services/feishu_messaging.py`
  - 消息发送与事件转发

---

## 4. 讨论上下文策略

当前采用：

**完整原文优先 + token 感知裁剪 + 最近原文 + 轮次总结 + 结构化状态 + 老历史检索**

执行顺序：

1. 优先尝试注入完整历史原文
2. 超出 Token 预算时退化为分层上下文：
   - `structured_state`
   - 最近完整原文
   - 最近轮次总结 `round_summaries`
   - 较老历史召回片段
3. Agent 与 Moderator 使用独立 Token 预算
4. 单条消息不做半句式硬截断

主持人会持续维护：

- `key_points`
- `agreements`
- `disagreements`
- `open_questions`
- `candidate_options`
- `risks`
- `next_focus`
- `unresolved_conflicts`
- `user_pinned_points`

---

## 5. 快速启动

### 5.1 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 5.2 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

或：

```bash
python run_server.py --host 0.0.0.0 --port 8000
```

启动后地址：

- API Base: `http://127.0.0.1:8000/api/v1`
- Health: `http://127.0.0.1:8000/healthz`

### 5.3 Demo 数据

```bash
curl -X POST http://127.0.0.1:8000/api/v1/demo/bootstrap
```

---

## 6. 关键环境变量

后端环境变量统一使用 `APP_` 前缀。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_DATABASE_URL` | `sqlite+aiosqlite:///./backend.db` | 主数据库连接 |
| `APP_SECRET_KEY` | `dev-secret-key` | 敏感字段编码前缀 |
| `APP_WORKSPACE_ROOT` | `<cwd>` | 运行工作区根目录 |
| `APP_ARTIFACT_ROOT` | `<cwd>/artifacts` | Skill / MCP / Checkpoint / 检索产物目录 |
| `APP_MIN_DISCUSSION_ROUNDS` | `2` | 最小讨论轮数 |
| `APP_DISCUSSION_AGENT_PROMPT_TOKEN_BUDGET` | `3200` | Agent Prompt Token 预算 |
| `APP_DISCUSSION_MODERATOR_PROMPT_TOKEN_BUDGET` | `4200` | Moderator Prompt Token 预算 |
| `APP_DISCUSSION_RECENT_FULL_MESSAGES` | `6` | 最近完整消息保留数 |
| `APP_DISCUSSION_HISTORY_RETRIEVAL_ITEMS` | `6` | 较老历史回填条数上限 |
| `APP_DISCUSSION_HYBRID_RETRIEVAL_ENABLED` | `true` | 是否启用混合检索 |
| `APP_DISCUSSION_VECTOR_SEARCH_ENABLED` | `true` | 是否启用 sqlite-vec |
| `APP_DISCUSSION_VECTOR_DIMENSIONS` | `128` | 轻量哈希向量维度 |
| `APP_DISCUSSION_RETRIEVAL_FTS_LIMIT` | `8` | FTS 候选数上限 |
| `APP_DISCUSSION_RETRIEVAL_VECTOR_LIMIT` | `8` | 向量候选数上限 |
| `APP_DISCUSSION_RETRIEVAL_SQLITE_PATH` | `artifacts/discussion_retrieval.sqlite` | 检索侧车 SQLite 路径 |
| `APP_CLEANUP_RUN_WORKSPACE_ON_FINISH` | `true` | Run 结束后清理工作区 |
| `APP_SKILL_PROMPT_CHAR_LIMIT` | `1200` | 单个 Skill Prompt 长度上限 |
| `APP_SKILL_PROMPT_TOTAL_CHAR_LIMIT` | `3200` | Skill Prompt 总长度上限 |
| `APP_REPORT_MESSAGE_CHAR_LIMIT` | `400` | 最终报告单条摘要长度上限 |
| `APP_LANGGRAPH_CHECKPOINT_PATH` | `artifacts/langgraph_checkpoints.sqlite` | LangGraph checkpoint 路径 |
| `APP_LANGGRAPH_RECOVER_ACTIVE_RUNS` | `true` | 启动时恢复活动 Run |
| `APP_LANGGRAPH_MODERATOR_TIMEOUT_SECONDS` | `20` | 主持人阶段超时秒数 |
| `APP_LANGGRAPH_MOCK_RESPONSE_DELAY_MS` | `0` | mock Provider 延迟模拟 |

---

## 7. 数据与产物

后端会持久化或生成以下数据：

- SQLite 主库 `backend.db`
- 讨论检索侧车库 `artifacts/discussion_retrieval.sqlite`
- LangGraph checkpoints `artifacts/langgraph_checkpoints.sqlite`
- Skill / MCP 上传产物
- Run 工作区副本
- 运行事件、最终报告、Tool Log
- 后端日志 `backend/backend-app.log`

---

## 8. 开发说明

- 默认数据库为 SQLite，适合本地开发与联调
- jar 型 MCP 依赖本机 Java 环境
- Git 工具依赖本机可用 `git`
- Feishu 当前仅支持明文事件模式
- `mock` Provider 适合演示与回归验证
- 若 `sqlite-vec` 不可用，会自动回退为 FTS / lexical 检索，不影响主流程

---

## 9. 相关文档

- 根目录 `README.md`：项目总览与前后端协同说明
- 根目录 `FEISHU_SETUP.md`：飞书联调说明
