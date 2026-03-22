# AlignHub Backend

AlignHub 后端基于 **FastAPI + SQLAlchemy + LangGraph**，提供：

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

- `app/runtime_langgraph.py`：LangGraph 运行编排、轮次总结 / 结构化状态维护、主持人裁决
- `app/runtime_common.py`：运行控制共享状态、事件服务、主持人结构化输出模型
- `app/services/discussion_prompts.py`：分层讨论上下文组装、Token 估算、老历史检索与最终报告拼装
- `app/services/builtin_tools.py`：内置工具注册
- `app/feishu.py`：Feishu 门面
- `app/services/langgraph_models.py`：模型运行时适配
- `app/services/mcp_runtime.py`：MCP 运行时
- `app/services/workspace.py`：运行工作区复制与清理
- `app/services/feishu_*.py`：Feishu 细分服务

## 讨论上下文策略

当前讨论上下文采用：**完整原文优先 + token 感知裁剪 + 最近原文 + 轮次总结 + 结构化状态 + 老历史混合检索**。

- 优先注入完整历史原文；如果 Prompt 预算允许，直接把完整历史喂给 Agent / Moderator
- 超出预算后，退化为分层上下文：`structured_state` + 最近完整原文 + 最近轮次总结 + 较老历史混合检索结果
- 老历史检索默认采用 **SQLite FTS + sqlite-vec（可用时）+ 词项回退** 的混合策略；当 `sqlite-vec` 不可加载时会自动退回 FTS/词项检索
- 混合检索的融合排序对 **FTS 命中** 保持更高权重；遇到模块名、错误码、路径等精确术语时，会进一步提升 lexical 权重
- 轻量哈希向量会对 **Entity 术语**（错误码、模块名、路径、数字字母混合 token）做二次加权；查询侧还会把 `topic` / `agreements` / `user_pinned_points` 作为静态向量锚点参与召回
- 不再对单条消息做半句式硬截断，避免模型误判上下文“被截断”
- Saliency 采用**阶段感知动态权重**：讨论前期更强调问题/风险暴露，后期更强调结论/共识收敛
- Density Penalty 增加了**代码 / JSON / 配置白名单保护**：长代码块、长 JSON、配置片段不会因为“字数多但关键词少”而被误判为低信息密度
- Semantic TTL 也会与讨论阶段联动：进入后期后，低优先级且长期无回音的 open question / candidate option 会更积极归档
- 主持人每轮输出结构化字段：`key_points`、`agreements`、`disagreements`、`open_questions`、`candidate_options`、`risks`
- 最终报告会携带 `structured_state` 与 `round_summaries`，便于回放和后续分析
- `state_patch_log` 会记录 Moderator adoption 观测字段，便于排查某类 Agent Patch 长期不被采纳的问题
- 对 `conflicted` patch，Moderator Prompt 会额外注入**冲突解决模板**，要求结合相关轮次原文给出明确裁决
- 如果 Moderator 对 conflicted patch 仍未给出清晰结论，运行时会将其提升为 `unresolved_conflict`，写入 `structured_state.unresolved_conflicts`，并把该议题置顶到下一轮 `next_focus`
- 用户通过 `user_input` 注入时可传 `mark_important=true`，该消息会获得 Saliency Max，并写入 `structured_state.user_pinned_points` 作为长期驻留关注点
- 前端实时页支持**点选历史消息一键设为重点**；未解决冲突支持展开查看结构化详情，便于快速核对 Moderator 裁决失败的上下文

### 启动时的检索运行态检测

后端启动时会主动探测讨论检索运行态，并输出一条启动日志，明确说明：

- 当前模式：`lexical_only` / `fts_only` / `hybrid_fts_vector`
- `fts=on/off`
- `vector=on/off`
- `vec_version`
- 检索侧车 SQLite 路径
- 向量维度
- 回退原因（如果没有启用向量）

典型日志示例：

```text
Discussion retrieval runtime: mode=hybrid_fts_vector fts=on vector=on vec_version=v0.1.7 ...
Discussion retrieval runtime: mode=fts_only fts=on vector=off vec_version=- ... reason=sqlite-vec unavailable, using fts + lexical fallback
```

这意味着即使 `sqlite-vec` 在当前环境不可用，系统仍会保留 FTS/词项回退，不会影响讨论主流程启动。

### 用户重点关注注入

`POST /api/v1/runs/{run_id}/user-input` 支持：

```json
{
  "message": "请始终优先关注回滚链路完整性",
  "source": "user",
  "pause": false,
  "mark_important": true
}
```

当 `mark_important=true` 时：

- 该消息会获得 Saliency Max
- 会被写入 `structured_state.user_pinned_points`
- 检索层会把它作为后续轮次的静态锚点之一

### 相关环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_DISCUSSION_AGENT_PROMPT_TOKEN_BUDGET` | `3200` | Agent Prompt Token 预算 |
| `APP_DISCUSSION_MODERATOR_PROMPT_TOKEN_BUDGET` | `4200` | 主持人 Prompt Token 预算 |
| `APP_DISCUSSION_RECENT_FULL_MESSAGES` | `6` | 最近完整原文消息保留数 |
| `APP_DISCUSSION_HISTORY_RETRIEVAL_ITEMS` | `6` | 老历史检索回填条数上限 |
| `APP_DISCUSSION_HYBRID_RETRIEVAL_ENABLED` | `true` | 是否启用 SQLite 混合检索 |
| `APP_DISCUSSION_VECTOR_SEARCH_ENABLED` | `true` | 是否启用 sqlite-vec 向量召回 |
| `APP_DISCUSSION_VECTOR_DIMENSIONS` | `128` | 轻量哈希向量维度 |
| `APP_DISCUSSION_RETRIEVAL_FTS_LIMIT` | `8` | FTS 候选条数上限 |
| `APP_DISCUSSION_RETRIEVAL_VECTOR_LIMIT` | `8` | 向量候选条数上限 |
| `APP_DISCUSSION_RETRIEVAL_SQLITE_PATH` | `artifacts/discussion_retrieval.sqlite` | 检索侧车 SQLite 路径 |
| `APP_DISCUSSION_CONTEXT_MESSAGES` | `6` | 旧版固定消息窗口参数，兼容保留 |

## Demo

```bash
curl -X POST http://127.0.0.1:8000/api/v1/demo/bootstrap
```

## 说明

- 默认数据库：SQLite
- 默认会在 Run 结束后清理运行工作区
- Feishu 事件目前仅支持明文模式
- 讨论上下文默认启用分层 Token 感知裁剪与结构化状态复用

详细说明请查看仓库根目录 `README.md`。
