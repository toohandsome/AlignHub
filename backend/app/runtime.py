from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from agentscope.agent import ReActAgent
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock
from agentscope.pipeline import MsgHub
from agentscope.tool import ToolResponse, Toolkit
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import RealtimeBroker, settings
from app.db import SessionLocal
from app.entities import (
    AgentConfig,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentToolBinding,
    ChatSession,
    ChatSessionAgent,
    DiscussionEvent,
    DiscussionEventCounter,
    DiscussionRun,
    FinalReport,
    ModelConfig,
    ProviderConfig,
    ToolCallLog,
    ToolDefinition,
)
from app.services.discussion_prompts import (
    build_agent_turn_prompt,
    build_final_report,
    build_moderator_prompt,
    compose_agent_system_prompt,
    format_discussion_context,
    shorten_text,
)
from app.services.mcp_runtime import invoke_mcp_http, invoke_mcp_sse, invoke_mcp_stdio
from app.services.runtime_models import build_formatter, build_model
from app.services.workspace import cleanup_run_workspace, prepare_run_workspace
from app.tools import TOOL_REGISTRY, ToolRuntimeContext

logger = logging.getLogger(__name__)


def _serialize_tool_chunks(chunks: list) -> dict:
    """把工具流式输出整理成可持久化的结构。

    返回结果同时保留：
    - 原始块列表：便于前端展示结构化内容
    - 文本摘要：便于日志快速预览
    """
    texts: list[str] = []
    structured: list = []
    for chunk in chunks:
        structured.append(chunk)
        if isinstance(chunk, list):
            for block in chunk:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(str(block.get("text", "")))
        elif isinstance(chunk, dict) and chunk.get("type") == "text":
            texts.append(str(chunk.get("text", "")))
        else:
            texts.append(str(chunk))
    return {"chunks": structured, "text": "\n".join([text for text in texts if text]).strip()}


class ModeratorDecision(BaseModel):
    finished: bool = Field(description="Whether the discussion should finish")
    reason: str | None = Field(default=None)
    next_focus: str | None = Field(default=None)


@dataclass
class TurnContext:
    round_no: int
    agent_id: str
    agent_name: str


@dataclass
class PendingUserInput:
    text: str
    source: str = "user"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RunControlState:
    """单个 Run 的运行态控制器。

    负责管理：
    - 暂停 / 恢复
    - 停止
    - 用户补充输入
    - 当前正在执行的 Agent
    """
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self.pause_requested = False
        self.pending_inputs: list[PendingUserInput] = []
        self.active_agent: ReActAgent | None = None
        self.active_turn: TurnContext | None = None
        self._last_pause_request: tuple[str, str] | None = None
        self._pause_source: str | None = None
        self._resume_source: str | None = None
        self._stop_source: str | None = None

    async def attach_active_agent(self, agent: ReActAgent | None, turn: TurnContext | None) -> None:
        async with self._lock:
            self.active_agent = agent
            self.active_turn = turn

    async def clear_active_agent(self, agent: ReActAgent | None = None) -> None:
        async with self._lock:
            if agent is not None and self.active_agent is not agent:
                return
            self.active_agent = None
            self.active_turn = None

    async def request_pause(self, *, message: str | None = None, source: str = "user") -> bool:
        became_paused = False
        async with self._lock:
            normalized = (message or "").strip()
            if normalized:
                signature = (source, normalized)
                if self._last_pause_request != signature:
                    self.pending_inputs.append(PendingUserInput(text=normalized, source=source))
                    self._last_pause_request = signature
            if not self.pause_requested or self._resume_event.is_set():
                became_paused = True
                self._pause_source = source
            self.pause_requested = True
            self._resume_event.clear()
            active_agent = self.active_agent
        await self._interrupt_agent(active_agent)
        return became_paused

    async def add_input(self, *, message: str, source: str = "user", pause: bool = False) -> None:
        text = (message or "").strip()
        if not text:
            return
        if pause:
            await self.request_pause(message=text, source=source)
            return
        async with self._lock:
            self.pending_inputs.append(PendingUserInput(text=text, source=source))
            self._last_pause_request = None

    async def resume(self, *, message: str | None = None, source: str = "user") -> None:
        async with self._lock:
            if message and message.strip():
                self.pending_inputs.append(PendingUserInput(text=message.strip(), source=source))
            self.pause_requested = False
            self._resume_event.set()
            self._last_pause_request = None
            self._resume_source = source

    async def request_stop(self, *, source: str = "user") -> None:
        async with self._lock:
            self._stop_source = source
            active_agent = self.active_agent
        await self._interrupt_agent(active_agent)

    async def wait_until_resumed(self) -> None:
        await self._resume_event.wait()

    async def drain_inputs(self) -> list[PendingUserInput]:
        async with self._lock:
            pending = list(self.pending_inputs)
            self.pending_inputs.clear()
            return pending

    async def is_paused(self) -> bool:
        async with self._lock:
            return self.pause_requested or not self._resume_event.is_set()

    async def consume_pause_source(self) -> str | None:
        async with self._lock:
            source = self._pause_source
            self._pause_source = None
            return source

    async def consume_resume_source(self) -> str | None:
        async with self._lock:
            source = self._resume_source
            self._resume_source = None
            return source

    async def consume_stop_source(self, default: str | None = None) -> str | None:
        async with self._lock:
            source = self._stop_source or default
            self._stop_source = None
            return source

    async def _interrupt_agent(self, agent: ReActAgent | None) -> None:
        if agent is None:
            return
        try:
            await agent.interrupt()
        except Exception as exc:
            logger.warning("Failed to interrupt active agent: %s", exc)


class EventService:
    """运行事件服务。

    它负责把事件：
    1. 持久化到数据库
    2. 广播给 WebSocket 订阅者
    3. 转发给附加监听器（如飞书桥接）
    """
    def __init__(self, broker: RealtimeBroker) -> None:
        self.broker = broker
        self._locks: dict[str, asyncio.Lock] = {}
        self._listeners: list[Callable[[dict], Any]] = []

    def _lock(self, run_id: str) -> asyncio.Lock:
        if run_id not in self._locks:
            self._locks[run_id] = asyncio.Lock()
        return self._locks[run_id]

    def register_listener(self, listener: Callable[[dict], Any]) -> None:
        self._listeners.append(listener)

    async def _next_event_seq(self, db: AsyncSession, run_id: str) -> int:
        result = await db.execute(
            text(
                """
                INSERT INTO discussion_event_counters(run_id, next_seq)
                VALUES (:run_id, 2)
                ON CONFLICT(run_id) DO UPDATE
                SET next_seq = discussion_event_counters.next_seq + 1
                RETURNING next_seq - 1 AS seq
                """,
            ),
            {"run_id": run_id},
        )
        return int(result.scalar_one())

    async def publish(self, run_id: str, event_type: str, *, round_no: int = 0, agent_id: str | None = None, tool_name: str | None = None, payload: dict | None = None) -> dict:
        # 事件顺序必须在单个 run 内严格递增，因此这里按 run_id 加锁。
        payload = payload or {}
        async with self._lock(run_id):
            async with SessionLocal() as db:
                seq = await self._next_event_seq(db, run_id)
                row = DiscussionEvent(
                    run_id=run_id,
                    seq=seq,
                    round_no=round_no,
                    event_type=event_type,
                    agent_id=agent_id,
                    tool_name=tool_name,
                    payload_json=payload,
                )
                db.add(row)
                await db.commit()
                await db.refresh(row)
                event = {
                    "id": row.id,
                    "run_id": run_id,
                    "seq": seq,
                    "round_no": round_no,
                    "event_type": event_type,
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "created_at": row.created_at.isoformat(),
                }
        await self.broker.publish(run_id, event)
        for listener in self._listeners:
            try:
                result = listener(dict(event))
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                continue
        return event

    async def save_report(self, run_id: str, title: str, summary_markdown: str, conclusion_json: dict) -> FinalReport:
        async with SessionLocal() as db:
            report = FinalReport(run_id=run_id, title=title, summary_markdown=summary_markdown, conclusion_json=conclusion_json)
            db.add(report)
            await db.commit()
            await db.refresh(report)
        await self.publish(
            run_id,
            "report_generated",
            payload={
                "report_id": report.id,
                "title": report.title,
                "summary_markdown": report.summary_markdown,
                "conclusion_json": report.conclusion_json,
            },
        )
        return report


class AgentFactory:
    """负责构造运行时 Agent、工具箱以及 MCP 桥接能力。"""
    def _mcp_tool_name(self, name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower() or "server"
        return f"mcp_{slug}"

    def _make_text_response(self, text: str) -> ToolResponse:
        return ToolResponse(content=[TextBlock(type="text", text=text)], is_last=True)

    def _register_mcp_tools(self, toolkit: Toolkit, agent: AgentConfig, ctx: ToolRuntimeContext) -> None:
        """???????? MCP ????? Agent ??????"""
        for binding in agent.mcp_bindings:
            mcp = binding.mcp
            if not mcp.enabled:
                continue

            tool_name = self._mcp_tool_name(mcp.name)
            endpoint = (mcp.base_url or "").rstrip("/")
            command = mcp.command
            args = list(mcp.args_json or [])
            env_json = dict(mcp.env_json or {})

            async def mcp_bridge(action: str, payload_json: str = "{}", *, _mcp=mcp, _endpoint=endpoint, _command=command, _args=args, _env_json=env_json) -> ToolResponse:
                # ??? MCP ???????? stdio/http/sse ?????????
                """Invoke a mounted MCP endpoint.

                Args:
                    action (str): The action name to request from the MCP server.
                    payload_json (str): JSON string payload for the action.
                """

                try:
                    payload = json.loads(payload_json or "{}")
                except json.JSONDecodeError as exc:
                    return self._make_text_response(f"Invalid payload_json: {exc}")

                request_payload = {
                    "action": action,
                    "payload": payload,
                    "agent": {
                        "id": ctx.agent_id,
                        "name": ctx.agent_name,
                    },
                    "run": {
                        "run_id": ctx.run_id,
                        "round_no": ctx.round_no,
                    },
                    "mcp": {
                        "name": _mcp.name,
                        "transport_type": _mcp.transport_type,
                    },
                }

                if _mcp.transport_type == "stdio":
                    if not _command:
                        return self._make_text_response(f"MCP '{_mcp.name}' has no command configured.")
                    result = await invoke_mcp_stdio(
                        _command,
                        _args,
                        request_payload,
                        env_json=_env_json,
                        cwd=ctx.workspace_root,
                    )
                    return self._make_text_response(result)

                if _mcp.transport_type == "http":
                    if not _endpoint:
                        return self._make_text_response(f"MCP '{_mcp.name}' has no base_url configured.")
                    invoke_url = f"{_endpoint}/invoke"
                    result = await invoke_mcp_http(invoke_url, request_payload)
                    return self._make_text_response(result)

                if _mcp.transport_type == "sse":
                    if not _endpoint:
                        return self._make_text_response(f"MCP '{_mcp.name}' has no base_url configured.")
                    invoke_url = f"{_endpoint}/invoke"
                    result = await invoke_mcp_sse(invoke_url, request_payload)
                    return self._make_text_response(result)

                return self._make_text_response(f"Unsupported MCP transport type: {_mcp.transport_type}")

            mcp_bridge.__name__ = tool_name
            mcp_bridge.__doc__ = (
                f"Invoke mounted MCP server '{mcp.name}'. "
                f"Description: {mcp.description or 'No description'}. "
                "Provide action and payload_json."
            )
            toolkit.register_tool_function(mcp_bridge)

    def compose_agent_system_prompt(self, agent: AgentConfig) -> str:
        return compose_agent_system_prompt(
            agent,
            skill_char_limit=settings.skill_prompt_char_limit,
            skill_total_char_limit=settings.skill_prompt_total_char_limit,
        )

    def build_model(self, provider: ProviderConfig, model: ModelConfig):
        return build_model(provider, model)

    def build_formatter(self, provider_type: str, formatter_type: str, *, multi_agent: bool):
        return build_formatter(provider_type, formatter_type, multi_agent=multi_agent)

    def build_toolkit(
        self,
        agent: AgentConfig,
        *,
        run_id: str,
        workspace_root: str,
        round_no_getter: Callable[[], int] | None,
        on_tool_started: Callable[[str, str, dict], Any],
        on_tool_finished: Callable[[str, str, dict, list], Any],
        on_tool_failed: Callable[[str, str, dict, Exception], Any],
    ) -> Toolkit:
        """构建某个 Agent 的运行时工具箱。"""
        toolkit = Toolkit()
        ctx = ToolRuntimeContext(
            workspace_root=workspace_root,
            run_id=run_id,
            agent_id=agent.id,
            agent_name=agent.name,
            round_no_getter=round_no_getter,
        )
        for binding in agent.tool_bindings:
            TOOL_REGISTRY[binding.tool.name].register(toolkit, ctx)
        self._register_mcp_tools(toolkit, agent, ctx)

        async def middleware(kwargs: dict, next_handler):
            # 通过中间件统一记录工具开始、结束、失败事件，
            # 这样具体工具实现无需感知日志持久化细节。
            tool_call = kwargs["tool_call"]
            tool_name = tool_call["name"]
            tool_input = dict(tool_call.get("input", {}))
            tool_call_id = str(tool_call.get("id") or tool_call.get("tool_call_id") or uuid.uuid4().hex)
            await on_tool_started(tool_call_id, tool_name, tool_input)
            chunks = []
            try:
                async for chunk in await next_handler(**kwargs):
                    chunks.append(chunk.content)
                    yield chunk
            except Exception as exc:
                await on_tool_failed(tool_call_id, tool_name, tool_input, exc)
                raise
            await on_tool_finished(tool_call_id, tool_name, tool_input, chunks)

        toolkit.register_middleware(middleware)
        return toolkit

    def build_discussion_agent(
        self,
        agent: AgentConfig,
        *,
        run_id: str,
        workspace_root: str,
        round_no_getter: Callable[[], int] | None,
        on_tool_started: Callable[[str, str, dict], Any],
        on_tool_finished: Callable[[str, str, dict, list], Any],
        on_tool_failed: Callable[[str, str, dict, Exception], Any],
    ) -> ReActAgent:
        instance = ReActAgent(
            name=agent.name,
            sys_prompt=self.compose_agent_system_prompt(agent),
            model=self.build_model(agent.model.provider, agent.model),
            formatter=self.build_formatter(agent.model.provider.provider_type, agent.model.formatter_type, multi_agent=True),
            toolkit=self.build_toolkit(
                agent,
                run_id=run_id,
                workspace_root=workspace_root,
                round_no_getter=round_no_getter,
                on_tool_started=on_tool_started,
                on_tool_finished=on_tool_finished,
                on_tool_failed=on_tool_failed,
            ),
            memory=InMemoryMemory(),
            max_iters=agent.max_steps,
        )
        instance.set_console_output_enabled(False)
        return instance

    def build_single_reply_agent(self, agent: AgentConfig, *, workspace_root: str | None = None) -> ReActAgent:
        async def noop_started(tool_call_id: str, tool_name: str, tool_input: dict) -> None:
            return None

        async def noop_finished(tool_call_id: str, tool_name: str, tool_input: dict, chunks: list) -> None:
            return None

        async def noop_failed(tool_call_id: str, tool_name: str, tool_input: dict, exc: Exception) -> None:
            return None

        instance = ReActAgent(
            name=agent.name,
            sys_prompt=self.compose_agent_system_prompt(agent),
            model=self.build_model(agent.model.provider, agent.model),
            formatter=self.build_formatter(agent.model.provider.provider_type, agent.model.formatter_type, multi_agent=False),
            toolkit=self.build_toolkit(
                agent,
                run_id="feishu-direct",
                workspace_root=workspace_root or settings.workspace_root,
                round_no_getter=lambda: 0,
                on_tool_started=noop_started,
                on_tool_finished=noop_finished,
                on_tool_failed=noop_failed,
            ),
            memory=InMemoryMemory(),
            max_iters=agent.max_steps,
        )
        instance.set_console_output_enabled(False)
        return instance

    def build_moderator(self, agent: AgentConfig) -> ReActAgent:
        moderator = ReActAgent(
            name=agent.name,
            sys_prompt=(
                f"{self.compose_agent_system_prompt(agent)}\n\n"
                "你现在承担讨论主持人职责。"
                "请判断当前讨论是否已经足够收敛，可以结束。"
                "如果不能结束，请明确给出下一轮需要继续讨论的分歧点、待验证点或风险点。"
            ),
            model=self.build_model(agent.model.provider, agent.model),
            formatter=self.build_formatter(agent.model.provider.provider_type, agent.model.formatter_type, multi_agent=True),
            toolkit=Toolkit(),
            memory=InMemoryMemory(),
            max_iters=4,
        )
        moderator.set_console_output_enabled(False)
        return moderator



class DiscussionEngine:
    """多 Agent 讨论引擎。

    它负责完整的编排流程：
    - 逐轮调度发言
    - 暂停 / 恢复 / 注入用户输入
    - 主持人结束判断
    - 报告生成
    """
    def __init__(self, event_service: EventService) -> None:
        self.event_service = event_service
        self.factory = AgentFactory()
        self._controls: dict[str, RunControlState] = {}

    def control(self, run_id: str) -> RunControlState:
        if run_id not in self._controls:
            self._controls[run_id] = RunControlState()
        return self._controls[run_id]

    def clear_control(self, run_id: str) -> None:
        self._controls.pop(run_id, None)

    async def _persist_run_state(
        self,
        run_id: str,
        *,
        status: str,
        session_status: str | None = None,
        stop_reason: str | None = None,
        ended: bool = False,
    ) -> None:
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return
            run.status = status
            if stop_reason is not None:
                run.stop_reason = stop_reason
            if ended:
                run.ended_at = datetime.now(timezone.utc)
            if session_status:
                session = await db.get(ChatSession, run.session_id)
                if session:
                    session.status = session_status
            await db.commit()

    def _shorten(self, text: str, limit: int = 220) -> str:
        return shorten_text(text, limit)

    def _format_discussion_context(self, history: list[dict[str, Any]]) -> str:
        return format_discussion_context(history, max_messages=settings.discussion_context_messages)

    def _build_agent_turn_prompt(
        self,
        *,
        topic: str,
        round_no: int,
        max_rounds: int,
        agent_name: str,
        history: list[dict[str, Any]],
    ) -> str:
        return build_agent_turn_prompt(
            topic=topic,
            round_no=round_no,
            max_rounds=max_rounds,
            agent_name=agent_name,
            history=history,
            context_messages=settings.discussion_context_messages,
        )

    def _build_moderator_prompt(
        self,
        *,
        topic: str,
        round_no: int,
        max_rounds: int,
        history: list[dict[str, Any]],
    ) -> str:
        return build_moderator_prompt(
            topic=topic,
            round_no=round_no,
            max_rounds=max_rounds,
            history=history,
            context_messages=settings.discussion_context_messages,
        )

    def _build_final_report(
        self,
        *,
        session_name: str,
        topic: str,
        history: list[dict[str, Any]],
        rounds: int,
    ) -> tuple[str, str, dict]:
        return build_final_report(
            session_name=session_name,
            topic=topic,
            history=history,
            rounds=rounds,
            per_message_char_limit=settings.report_message_char_limit,
        )

    async def _broadcast_user_input(
        self,
        *,
        run_id: str,
        round_no: int,
        pending: PendingUserInput,
        participants: list[ReActAgent],
        moderator: ReActAgent,
        history: list[dict[str, Any]],
    ) -> None:
        """把用户补充信息广播给所有参与者，并落库为事件。"""
        msg = Msg(
            "user",
            f"用户补充信息：{pending.text}",
            "user",
            metadata={"source": pending.source, "_external_input": True},
        )
        for runtime in [*participants, moderator]:
            await runtime.observe(msg)
        history.append(
            {
                "round_no": round_no,
                "agent_id": "user",
                "agent_name": "用户补充",
                "text": pending.text,
            },
        )
        await self.event_service.publish(
            run_id,
            "user_input",
            round_no=round_no,
            payload={"text": pending.text, "source": pending.source},
        )

    async def _inject_pending_inputs(
        self,
        *,
        run_id: str,
        round_no: int,
        control: RunControlState,
        participants: list[ReActAgent],
        moderator: ReActAgent,
        history: list[dict[str, Any]],
    ) -> None:
        for pending in await control.drain_inputs():
            await self._broadcast_user_input(
                run_id=run_id,
                round_no=round_no,
                pending=pending,
                participants=participants,
                moderator=moderator,
                history=history,
            )

    async def _pause_if_requested(
        self,
        *,
        run_id: str,
        round_no: int,
        control: RunControlState,
        participants: list[ReActAgent],
        moderator: ReActAgent,
        history: list[dict[str, Any]],
    ) -> None:
        if not await control.is_paused():
            await self._inject_pending_inputs(
                run_id=run_id,
                round_no=round_no,
                control=control,
                participants=participants,
                moderator=moderator,
                history=history,
            )
            return

        await self._persist_run_state(run_id, status="paused", session_status="paused")
        pause_source = await control.consume_pause_source() or "user"
        await self.event_service.publish(
            run_id,
            "run_status",
            round_no=round_no,
            payload={"status": "paused", "source": pause_source},
        )
        await self._inject_pending_inputs(
            run_id=run_id,
            round_no=round_no,
            control=control,
            participants=participants,
            moderator=moderator,
            history=history,
        )
        await control.wait_until_resumed()
        await self._persist_run_state(run_id, status="running", session_status="running")
        resume_source = await control.consume_resume_source() or "user"
        await self.event_service.publish(
            run_id,
            "run_status",
            round_no=round_no,
            payload={"status": "resumed", "source": resume_source},
        )
        await self._inject_pending_inputs(
            run_id=run_id,
            round_no=round_no,
            control=control,
            participants=participants,
            moderator=moderator,
            history=history,
        )

    async def execute(self, run_id: str) -> None:
        """执行一次完整的多 Agent 讨论运行。"""
        control = self.control(run_id)
        workspace_root = prepare_run_workspace(run_id)
        try:
            async with SessionLocal() as db:
                run = await self._load_run(db, run_id)
                if not run:
                    raise ValueError("Run not found")

                run.status = "running"
                run.started_at = datetime.now(timezone.utc)
                run.ended_at = None
                run.stop_reason = None
                run.session.status = "running"
                await db.commit()

                links = sorted(run.session.agents, key=lambda item: item.speak_order)
                ordered_agents = [link.agent for link in links]
                if not ordered_agents:
                    raise ValueError("Chat session has no agents")

                moderator_agent = next((agent for agent in ordered_agents if agent.is_moderator), None) or ordered_agents[0]
                discussion_agents = [agent for agent in ordered_agents if agent.id != moderator_agent.id]
                if not discussion_agents:
                    discussion_agents = [moderator_agent]

                discussion_history: list[dict[str, Any]] = []
                min_required_rounds = min(settings.min_discussion_rounds, run.session.max_rounds)
                current_turn: TurnContext | None = None

                async def tool_started(tool_call_id: str, tool_name: str, tool_input: dict) -> None:
                    if not current_turn:
                        return
                    async with SessionLocal() as tool_db:
                        tool_db.add(
                            ToolCallLog(
                                run_id=run_id,
                                round_no=current_turn.round_no,
                                agent_id=current_turn.agent_id,
                                call_id=tool_call_id,
                                tool_name=tool_name,
                                tool_input_json=tool_input,
                                tool_output_json={},
                                status="started",
                            ),
                        )
                        await tool_db.commit()

                async def tool_finished(tool_call_id: str, tool_name: str, tool_input: dict, chunks: list) -> None:
                    if not current_turn:
                        return
                    async with SessionLocal() as tool_db:
                        res = await tool_db.execute(
                            select(ToolCallLog).where(ToolCallLog.run_id == run_id, ToolCallLog.call_id == tool_call_id)
                        )
                        row = res.scalars().first()
                        if row:
                            row.tool_output_json = _serialize_tool_chunks(chunks)
                            row.status = "completed"
                            row.ended_at = datetime.now(timezone.utc)
                            await tool_db.commit()

                async def tool_failed(tool_call_id: str, tool_name: str, tool_input: dict, exc: Exception) -> None:
                    if not current_turn:
                        return
                    error_payload = {"error": str(exc), "type": type(exc).__name__}
                    async with SessionLocal() as tool_db:
                        res = await tool_db.execute(
                            select(ToolCallLog).where(ToolCallLog.run_id == run_id, ToolCallLog.call_id == tool_call_id)
                        )
                        row = res.scalars().first()
                        if row:
                            row.tool_output_json = error_payload
                            row.status = "failed"
                            row.ended_at = datetime.now(timezone.utc)
                            await tool_db.commit()
                    await self.event_service.publish(
                        run_id,
                        "tool_failed",
                        round_no=current_turn.round_no,
                        agent_id=current_turn.agent_id,
                        tool_name=tool_name,
                        payload={"call_id": tool_call_id, "input": tool_input, **error_payload},
                    )

                await self.event_service.publish(run_id, "run_status", payload={"status": "running"})

                runtime_agents: list[ReActAgent] = []
                for agent in discussion_agents:
                    runtime = self.factory.build_discussion_agent(
                        agent,
                        run_id=run_id,
                        workspace_root=workspace_root,
                        round_no_getter=lambda agent_id=agent.id: current_turn.round_no if current_turn and current_turn.agent_id == agent_id else 0,
                        on_tool_started=tool_started,
                        on_tool_finished=tool_finished,
                        on_tool_failed=tool_failed,
                    )
                    self._attach_print_hook(runtime, run_id, lambda: current_turn, agent.id)
                    runtime_agents.append(runtime)

                moderator = self.factory.build_moderator(moderator_agent)
                self._attach_print_hook(moderator, run_id, lambda: current_turn, moderator_agent.id)

                for round_no in range(1, run.session.max_rounds + 1):
                    run.current_round = round_no
                    await db.commit()
                    await self.event_service.publish(
                        run_id,
                        "run_status",
                        round_no=round_no,
                        payload={"status": "round_started", "round_no": round_no},
                    )

                    await self._pause_if_requested(
                        run_id=run_id,
                        round_no=round_no,
                        control=control,
                        participants=runtime_agents,
                        moderator=moderator,
                        history=discussion_history,
                    )

                    async with MsgHub(participants=[*runtime_agents, moderator]):
                        agent_index = 0
                        while agent_index < len(runtime_agents):
                            await self._pause_if_requested(
                                run_id=run_id,
                                round_no=round_no,
                                control=control,
                                participants=runtime_agents,
                                moderator=moderator,
                                history=discussion_history,
                            )
                            runtime = runtime_agents[agent_index]
                            agent = discussion_agents[agent_index]
                            current_turn = TurnContext(round_no=round_no, agent_id=agent.id, agent_name=agent.name)
                            await control.attach_active_agent(runtime, current_turn)
                            try:
                                reply_msg = await runtime(
                                    Msg(
                                        "system",
                                        self._build_agent_turn_prompt(
                                            topic=run.session.topic,
                                            round_no=round_no,
                                            max_rounds=run.session.max_rounds,
                                            agent_name=agent.name,
                                            history=discussion_history,
                                        ),
                                        "system",
                                    ),
                                )
                            finally:
                                await control.clear_active_agent(runtime)

                            if reply_msg and (reply_msg.metadata or {}).get("_is_interrupted"):
                                await self._pause_if_requested(
                                    run_id=run_id,
                                    round_no=round_no,
                                    control=control,
                                    participants=runtime_agents,
                                    moderator=moderator,
                                    history=discussion_history,
                                )
                                continue

                            text = reply_msg.get_text_content() if reply_msg else ""
                            if text:
                                discussion_history.append(
                                    {
                                        "round_no": round_no,
                                        "agent_id": agent.id,
                                        "agent_name": agent.name,
                                        "text": text,
                                    },
                                )
                            agent_index += 1

                    if round_no < min_required_rounds:
                        await self.event_service.publish(
                            run_id,
                            "run_status",
                            round_no=round_no,
                            payload={
                                "status": "moderator_decision",
                                "finished": False,
                                "reason": f"At least {min_required_rounds} rounds are required before finishing.",
                                "next_focus": "继续补充事实、风险与方案差异。",
                            },
                        )
                        continue

                    while True:
                        await self._pause_if_requested(
                            run_id=run_id,
                            round_no=round_no,
                            control=control,
                            participants=runtime_agents,
                            moderator=moderator,
                            history=discussion_history,
                        )
                        current_turn = TurnContext(round_no=round_no, agent_id=moderator_agent.id, agent_name=moderator_agent.name)
                        await control.attach_active_agent(moderator, current_turn)
                        try:
                            decision = await moderator(
                                Msg(
                                    "system",
                                    self._build_moderator_prompt(
                                        topic=run.session.topic,
                                        round_no=round_no,
                                        max_rounds=run.session.max_rounds,
                                        history=discussion_history,
                                    ),
                                    "system",
                                ),
                                structured_model=ModeratorDecision,
                            )
                        finally:
                            await control.clear_active_agent(moderator)

                        if decision and (decision.metadata or {}).get("_is_interrupted"):
                            await self._pause_if_requested(
                                run_id=run_id,
                                round_no=round_no,
                                control=control,
                                participants=runtime_agents,
                                moderator=moderator,
                                history=discussion_history,
                            )
                            continue
                        decision_payload = dict(decision.metadata or {})
                        await self.event_service.publish(
                            run_id,
                            "run_status",
                            round_no=round_no,
                            payload={"status": "moderator_decision", **decision_payload},
                        )
                        break

                    if decision_payload.get("finished"):
                        break

                report_title, report_markdown, conclusion_json = self._build_final_report(
                    session_name=run.session.name,
                    topic=run.session.topic,
                    history=discussion_history,
                    rounds=run.current_round,
                )
                await self.event_service.save_report(
                    run_id,
                    title=report_title,
                    summary_markdown=report_markdown,
                    conclusion_json=conclusion_json,
                )
                await self._persist_run_state(run_id, status="finished", session_status="finished", ended=True)
                await self.event_service.publish(run_id, "run_status", payload={"status": "finished"})
        except asyncio.CancelledError:
            await self._persist_run_state(run_id, status="stopped", session_status="stopped", stop_reason="Stopped by user", ended=True)
            stop_source = await control.consume_stop_source(default="user")
            await self.event_service.publish(
                run_id,
                "run_status",
                payload={"status": "stopped", "source": stop_source},
            )
            raise
        except Exception as exc:
            await self._persist_run_state(run_id, status="failed", session_status="failed", stop_reason=str(exc), ended=True)
            await self.event_service.publish(run_id, "error", payload={"message": str(exc)})
            raise
        finally:
            self.clear_control(run_id)
            if settings.cleanup_run_workspace_on_finish:
                cleanup_run_workspace(run_id)

    async def _load_run(self, db: AsyncSession, run_id: str) -> DiscussionRun | None:
        res = await db.execute(
            select(DiscussionRun)
            .options(
                selectinload(DiscussionRun.session)
                .selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.model)
                .selectinload(ModelConfig.provider),
                selectinload(DiscussionRun.session)
                .selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.tool_bindings)
                .selectinload(AgentToolBinding.tool),
                selectinload(DiscussionRun.session)
                .selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.skill_bindings)
                .selectinload(AgentSkillBinding.skill),
                selectinload(DiscussionRun.session)
                .selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.mcp_bindings)
                .selectinload(AgentMCPBinding.mcp),
                selectinload(DiscussionRun.session)
                .selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.feishu_bot),
            )
            .where(DiscussionRun.id == run_id)
        )
        return res.scalar_one_or_none()

    def _attach_print_hook(self, runtime_agent: ReActAgent, run_id: str, turn_getter: Callable[[], TurnContext | None], fixed_agent_id: str | None) -> None:
        event_service = self.event_service

        async def post_print(self, kwargs: dict, output):
            msg = kwargs["msg"]
            last = kwargs.get("last", True)
            if (msg.metadata or {}).get("_is_interrupted"):
                return
            turn = turn_getter()
            round_no = turn.round_no if turn else 0
            agent_id = fixed_agent_id or (turn.agent_id if turn else None)
            if msg.has_content_blocks("tool_use"):
                for block in msg.get_content_blocks("tool_use"):
                    call_id = block.get("id") or block.get("tool_call_id")
                    await event_service.publish(
                        run_id,
                        "tool_started",
                        round_no=round_no,
                        agent_id=agent_id,
                        tool_name=block["name"],
                        payload={"message_id": msg.id, "call_id": call_id, "input": block.get("input", {})},
                    )
            elif msg.has_content_blocks("tool_result"):
                for block in msg.get_content_blocks("tool_result"):
                    call_id = block.get("id") or block.get("tool_call_id") or block.get("tool_use_id")
                    await event_service.publish(
                        run_id,
                        "tool_completed",
                        round_no=round_no,
                        agent_id=agent_id,
                        tool_name=block["name"],
                        payload={"message_id": msg.id, "call_id": call_id, "output": block.get("output", [])},
                    )
            elif last and msg.get_text_content():
                await event_service.publish(
                    run_id,
                    "message_completed",
                    round_no=round_no,
                    agent_id=agent_id,
                    payload={
                        "message_id": msg.id,
                        "agent_name": msg.name,
                        "role": msg.role,
                        "text": msg.get_text_content(),
                        "metadata": msg.metadata,
                    },
                )

        runtime_agent.register_instance_hook("post_print", f"publish_{run_id}", post_print)


class RunManager:
    """Run 生命周期管理器。"""

    def __init__(self, event_service: EventService) -> None:
        self.event_service = event_service
        self.engine = DiscussionEngine(event_service)
        self._tasks: dict[str, asyncio.Task] = {}
        self._session_start_locks: dict[str, asyncio.Lock] = {}

    def _session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_start_locks:
            self._session_start_locks[session_id] = asyncio.Lock()
        return self._session_start_locks[session_id]

    def _track_task(self, run_id: str, task: asyncio.Task) -> None:
        self._tasks[run_id] = task

        def _cleanup(_task: asyncio.Task) -> None:
            self._tasks.pop(run_id, None)

        task.add_done_callback(_cleanup)

    async def _sync_session_status(self, db: AsyncSession, session_id: str) -> None:
        session = await db.get(ChatSession, session_id)
        if not session:
            return
        res = await db.execute(
            select(DiscussionRun.status)
            .where(DiscussionRun.session_id == session_id)
            .order_by(DiscussionRun.created_at.desc())
        )
        latest = res.first()
        session.status = str(latest[0]) if latest else "draft"

    async def start(self, session_id: str, *, notify_feishu: bool = True) -> DiscussionRun:
        async with self._session_lock(session_id):
            async with SessionLocal() as db:
                session = await db.get(ChatSession, session_id)
                if not session:
                    raise ValueError("Chat session not found")
                active = await db.execute(
                    select(DiscussionRun)
                    .where(DiscussionRun.session_id == session_id, DiscussionRun.status.in_(["draft", "running", "paused"]))
                    .order_by(DiscussionRun.created_at.desc())
                )
                if active.scalars().first():
                    raise ValueError("Chat session already has an active run")
                run = DiscussionRun(session_id=session_id, status="draft", current_round=0, notify_feishu=notify_feishu)
                session.status = "running"
                db.add(run)
                try:
                    await db.flush()
                    await db.commit()
                except IntegrityError as exc:
                    await db.rollback()
                    raise ValueError("Chat session already has an active run") from exc
                result = await db.execute(
                    select(DiscussionRun)
                    .options(selectinload(DiscussionRun.reports))
                    .where(DiscussionRun.id == run.id)
                )
                run = result.scalar_one()
        self._track_task(run.id, asyncio.create_task(self.engine.execute(run.id)))
        return run

    async def stop(self, run_id: str, *, source: str = "user") -> None:
        task = self._tasks.get(run_id)
        if task and not task.done():
            control = self.engine.control(run_id)
            await control.request_stop(source=source)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Run %s raised during stop: %s", run_id, exc)

        should_publish = False
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                self.engine.clear_control(run_id)
                return
            if run.status in {"finished", "failed", "stopped"}:
                return
            run.status = "stopped"
            run.ended_at = datetime.now(timezone.utc)
            run.stop_reason = "Stopped by user"
            session = await db.get(ChatSession, run.session_id)
            if session:
                session.status = "stopped"
            await db.commit()
            should_publish = True
        if should_publish:
            await self.event_service.publish(run_id, "run_status", payload={"status": "stopped", "source": source})

    async def pause(self, run_id: str, *, message: str | None = None, source: str = "user") -> DiscussionRun | None:
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return None
            if run.status in {"finished", "failed", "stopped"}:
                raise ValueError("Run is no longer active")
        control = self.engine.control(run_id)
        became_paused = await control.request_pause(message=message, source=source)
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                self.engine.clear_control(run_id)
                return None
            if run.status in {"finished", "failed", "stopped"}:
                self.engine.clear_control(run_id)
                raise ValueError("Run is no longer active")
            if became_paused and run.status != "paused":
                run.status = "paused"
                session = await db.get(ChatSession, run.session_id)
                if session:
                    session.status = "paused"
                await db.commit()
            await db.refresh(run)
            return run

    async def resume(self, run_id: str, *, message: str | None = None, source: str = "user") -> DiscussionRun | None:
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return None
            if run.status in {"finished", "failed", "stopped"}:
                raise ValueError("Run is no longer active")
        control = self.engine.control(run_id)
        await control.resume(message=message, source=source)
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                self.engine.clear_control(run_id)
                return None
            if run.status in {"finished", "failed", "stopped"}:
                self.engine.clear_control(run_id)
                raise ValueError("Run is no longer active")
            if run.status == "paused":
                run.status = "running"
                session = await db.get(ChatSession, run.session_id)
                if session:
                    session.status = "running"
                await db.commit()
            await db.refresh(run)
            return run

    async def inject_user_input(
        self,
        run_id: str,
        *,
        message: str,
        source: str = "user",
        pause: bool = False,
    ) -> DiscussionRun | None:
        if not (message or "").strip():
            raise ValueError("Message is required")
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return None
            if run.status in {"finished", "failed", "stopped"}:
                raise ValueError("Run is no longer active")
        control = self.engine.control(run_id)
        await control.add_input(message=message, source=source, pause=pause)
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                self.engine.clear_control(run_id)
                return None
            if run.status in {"finished", "failed", "stopped"}:
                self.engine.clear_control(run_id)
                raise ValueError("Run is no longer active")
            if pause and run.status not in {"finished", "failed", "stopped", "paused"}:
                run.status = "paused"
                session = await db.get(ChatSession, run.session_id)
                if session:
                    session.status = "paused"
                await db.commit()
            await db.refresh(run)
            return run

    async def get_run(self, run_id: str) -> DiscussionRun | None:
        async with SessionLocal() as db:
            res = await db.execute(select(DiscussionRun).options(selectinload(DiscussionRun.reports)).where(DiscussionRun.id == run_id))
            return res.scalar_one_or_none()

    async def find_active_run_for_session(self, session_id: str) -> DiscussionRun | None:
        async with SessionLocal() as db:
            res = await db.execute(
                select(DiscussionRun)
                .where(DiscussionRun.session_id == session_id, DiscussionRun.status.in_(["draft", "running", "paused"]))
                .order_by(DiscussionRun.created_at.desc())
            )
            return res.scalars().first()

    async def list_runs(self, *, session_id: str | None = None) -> list[DiscussionRun]:
        async with SessionLocal() as db:
            stmt = select(DiscussionRun).options(selectinload(DiscussionRun.reports)).order_by(DiscussionRun.created_at.desc())
            if session_id:
                stmt = stmt.where(DiscussionRun.session_id == session_id)
            res = await db.execute(stmt)
            return list(res.scalars().all())

    async def delete_run(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task and not task.done():
            await self.stop(run_id, source="delete")

        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                cleanup_run_workspace(run_id)
                self.engine.clear_control(run_id)
                return False
            session_id = run.session_id
            await db.delete(run)
            await db.flush()
            await self._sync_session_status(db, session_id)
            await db.commit()
        self._tasks.pop(run_id, None)
        self.engine.clear_control(run_id)
        cleanup_run_workspace(run_id)
        return True

    async def list_events(self, run_id: str) -> list[DiscussionEvent]:
        async with SessionLocal() as db:
            res = await db.execute(select(DiscussionEvent).where(DiscussionEvent.run_id == run_id).order_by(DiscussionEvent.seq.asc()))
            return list(res.scalars().all())

    async def get_report(self, run_id: str) -> FinalReport | None:
        async with SessionLocal() as db:
            res = await db.execute(select(FinalReport).where(FinalReport.run_id == run_id).order_by(FinalReport.created_at.desc()))
            return res.scalars().first()

    async def list_tool_logs(self, run_id: str) -> list[ToolCallLog]:
        async with SessionLocal() as db:
            res = await db.execute(select(ToolCallLog).where(ToolCallLog.run_id == run_id).order_by(ToolCallLog.started_at.asc()))
            return list(res.scalars().all())

    async def ask_agent_in_session(self, session_id: str, agent_name: str, question: str) -> dict:
        async with SessionLocal() as db:
            session = await self._load_session_for_reply(db, session_id)
            if not session:
                raise ValueError("Chat session not found")
            links = sorted(session.agents, key=lambda item: item.speak_order)
            matched = next(
                (
                    link.agent
                    for link in links
                    if link.agent.name == agent_name or link.agent.name.lower() == agent_name.lower()
                ),
                None,
            )
            if not matched:
                raise ValueError(f"Agent not found in session: {agent_name}")

            runtime = self.engine.factory.build_single_reply_agent(matched, workspace_root=settings.workspace_root)
            reply = await runtime(
                Msg(
                    "user",
                    (
                        f"当前会话主题：{session.topic}\n"
                        f"用户正在飞书群中单独向你提问。请只以“{matched.name}”的角色口吻直接回答，简洁且可执行。\n\n"
                        f"用户问题：{question}"
                    ),
                    "user",
                ),
            )
            text = reply.get_text_content() if reply else ""
            return {"agent_id": matched.id, "agent_name": matched.name, "text": text}

    async def _load_session_for_reply(self, db: AsyncSession, session_id: str) -> ChatSession | None:
        res = await db.execute(
            select(ChatSession)
            .options(
                selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.model)
                .selectinload(ModelConfig.provider),
                selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.tool_bindings)
                .selectinload(AgentToolBinding.tool),
                selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.skill_bindings)
                .selectinload(AgentSkillBinding.skill),
                selectinload(ChatSession.agents)
                .selectinload(ChatSessionAgent.agent)
                .selectinload(AgentConfig.mcp_bindings)
                .selectinload(AgentMCPBinding.mcp),
            )
            .where(ChatSession.id == session_id)
        )
        return res.scalar_one_or_none()


async def sync_builtin_tools() -> None:
    async with SessionLocal() as db:
        existing = {row.name: row for row in (await db.execute(select(ToolDefinition))).scalars().all()}
        for plugin in TOOL_REGISTRY.values():
            if plugin.name in existing:
                row = existing[plugin.name]
                row.category = plugin.category
                row.description = plugin.description
                row.schema_json = {"name": plugin.name}
                row.builtin = True
                row.enabled = True
            else:
                db.add(
                    ToolDefinition(
                        name=plugin.name,
                        category=plugin.category,
                        description=plugin.description,
                        schema_json={"name": plugin.name},
                        builtin=True,
                        enabled=True,
                    ),
                )
        await db.commit()
