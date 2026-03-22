# LangGraph 迁移设计稿（第一阶段）

## 1. 目标

在 **保持现有 API / DB / WebSocket / Feishu 契约不变** 的前提下，引入一套可并行切换的 LangGraph 运行时，逐步替代当前基于 AgentScope 的运行编排。

第一阶段目标：

1. 保留 `RunManager` 对外接口：`start / pause / resume / stop / user-input / events / report / tool-logs`
2. 新增 `langgraph` 运行时，不影响默认 `agentscope` 运行时
3. 继续使用现有：
   - `DiscussionRun / DiscussionEvent / ToolCallLog / FinalReport`
   - `EventService`
   - `FeishuBridgeService`
   - 前端 Run 详情与回放页
4. 将 AgentScope 的 **MsgHub 广播语义** 重建为 **LangGraph shared state + node/edge 路由**

---

## 2. 并行运行时方案

新增配置：

- `APP_RUNTIME_ENGINE=agentscope|langgraph`

启动时根据配置选择：

- `agentscope` → 现有 `app.runtime.RunManager`
- `langgraph` → 新增 `app.runtime_langgraph.RunManager`

这样可以：

- 降低一次性切换风险
- 支持同一套前端/后端接口进行对比验证
- 允许在 demo、测试环境先切 LangGraph

---

## 3. LangGraph 状态模型

第一阶段 `DiscussionState`：

- `run_id`
- `session_id`
- `session_name`
- `topic`
- `max_rounds`
- `min_required_rounds`
- `round_no`
- `agent_index`
- `discussion_agent_ids`
- `moderator_agent_id`
- `discussion_history`
- `workspace_root`
- `finished`
- `moderator_decision`

说明：

- `discussion_history` 替代 AgentScope MsgHub 中隐式共享消息通道
- `agent_index + round_no` 替代 MsgHub 内部轮转语义
- `workspace_root` 保持每次 Run 的隔离工作区
- `moderator_decision` 作为图内条件路由依据

---

## 4. 节点设计

### 4.1 `round_start`
职责：
- 持久化 `current_round`
- 发布 `run_status(round_started)`

### 4.2 `pause_gate`
职责：
- 检查 `RunControlState.pause_requested`
- 如需暂停，调用 LangGraph `interrupt()`
- 恢复后发布 `run_status(resumed)`

说明：
- 第一阶段的暂停是 **safe-point pause**，在节点边界生效
- 不追求 AgentScope `agent.interrupt()` 的“模型调用中断”能力

### 4.3 `inject_inputs`
职责：
- 读取 `RunControlState.pending_inputs`
- 写入 `discussion_history`
- 发布 `user_input` 事件

### 4.4 `agent_turn`
职责：
- 根据 `agent_index` 取当前 Agent
- 组装系统提示词 + 当前轮 prompt
- 调用 LangChain/LangGraph agent 执行单轮回复
- 写入 `discussion_history`
- 发布 `message_completed`
- 若发生工具调用，写入 `ToolCallLog` 并发布工具事件

### 4.5 `force_continue`
职责：
- 在最小轮次未满足时，跳过 moderator 的 finish 判断
- 发布与现有实现一致的 `moderator_decision(finished=false)` 事件

### 4.6 `moderator_turn`
职责：
- 生成结构化 `ModeratorDecision`
- 写入 `moderator_decision`
- 发布 `run_status(moderator_decision)`

### 4.7 `next_round`
职责：
- `round_no += 1`
- `agent_index = 0`

### 4.8 `report`
职责：
- 调用现有 `build_final_report()`
- 持久化 `FinalReport`
- 将 Run 标记为 finished
- 发布 `report_generated` / `run_status(finished)`

---

## 5. 路由设计

```text
START
  -> round_start
  -> pause_gate
  -> inject_inputs
  -> [agent_index < discussion_agent_count] ? agent_turn : moderator_or_force_continue

agent_turn
  -> pause_gate

moderator_or_force_continue
  -> force_continue (if round_no < min_required_rounds)
  -> moderator_turn (otherwise)

force_continue
  -> next_round

moderator_turn
  -> report      (if finished=true)
  -> report      (if round_no >= max_rounds)
  -> next_round  (otherwise)

next_round
  -> round_start

report
  -> END
```

---

## 6. Tool / MCP 迁移策略

第一阶段新增 `app.services.langgraph_tools`：

### 内置 Tool
将以下 AgentScope Toolkit 工具改造成 LangChain StructuredTool：

- `topic_probe`
- `list_files`
- `read_file`
- `write_file`
- `edit_file`
- `git_status`
- `git_log`
- `git_diff`
- `git_add`
- `git_commit`

### MCP Tool
沿用现有：

- `invoke_mcp_stdio`
- `invoke_mcp_http`
- `invoke_mcp_sse`

对每次调用统一包装：

- `tool_started`
- `tool_completed`
- `tool_failed`
- `ToolCallLog` 持久化

---

## 7. Model 迁移策略

新增 `app.services.langgraph_models`：

- `openai/openrouter/openai_compatible` → `ChatOpenAI`
- `azure` → `AzureChatOpenAI`
- `anthropic` → `ChatAnthropic`
- `ollama` → `ChatOllama`
- `mock` → 第一阶段保留本地 mock 推理分支（不走真实 LangChain model）

### 兼容字段处理
以下字段保留，但转为“兼容/过渡字段”：

- `formatter_type`
- `memory_strategy`
- `is_reporter`

说明：
- LangGraph 路径中 `formatter_type` 不再是核心概念
- `memory_strategy` 由 graph state/checkpointer 逐步接管
- `is_reporter` 当前仍不直接驱动最终报告生成

---

## 8. API/前端兼容策略

保持不变：

- `/runs/*`
- `/chat-sessions/*`
- `/ws/runs/{run_id}`
- 事件类型：
  - `message_completed`
  - `tool_started`
  - `tool_completed`
  - `tool_failed`
  - `run_status`
  - `user_input`
  - `report_generated`
  - `error`

前端第一阶段只做轻微文案调整：

- 将 `formatter_type / memory_strategy / reporter` 标记为兼容字段
- 不修改 Run 详情 / 回放 / Feishu 交互逻辑

---

## 9. 风险与已知差异

### 9.1 暂停能力差异
AgentScope 当前具备 `agent.interrupt()`；LangGraph 第一阶段只支持 safe-point pause。

### 9.2 MsgHub 不是 1:1 替换
LangGraph 无原生 MsgHub，需要通过 shared state 手工表达广播/上下文。

### 9.3 Mock provider 能力先保底，不追求完整 tool-use 仿真
第一阶段主要保证：
- 讨论流程可跑通
- moderator 可决策
- 前端契约不变

### 9.4 公共运行时基座尚未抽离
第一阶段会共享部分现有 `runtime.py` 中的组件；后续再抽出 `runtime_common.py`。

---

## 10. 第一阶段代码落点

新增：

- `app/runtime_factory.py`
- `app/runtime_langgraph.py`
- `app/services/langgraph_models.py`
- `app/services/langgraph_tools.py`
- `backend/docs/langgraph_migration_design.md`

修改：

- `app/core.py`
- `app/main.py`
- `app/routes/common.py`
- `backend/requirements.txt`
- 部分前端表单文案

---

## 11. 第二阶段建议

1. 抽出 `runtime_common.py`
2. 用 SQLite/Postgres checkpointer 替换第一阶段内存 checkpointer
3. 将 `ask_agent_in_session`、Feishu 单聊答复完全迁移到 LangGraph 路径
4. 清理前端兼容字段
5. 下线 AgentScope 依赖
