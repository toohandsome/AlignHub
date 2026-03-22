from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    ToolCallLog,
)


class RunPersistenceService:
    """封装 Run 相关数据库读写。

    目标是把执行层和 ORM 细节隔离开，便于生命周期层与节点层复用。
    """

    async def persist_control_state(self, run_id: str, snapshot: dict) -> None:
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return
            run.control_state_json = dict(snapshot or {})
            await db.commit()

    async def clear_persisted_control_state(self, run_id: str) -> None:
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return
            run.control_state_json = {}
            await db.commit()

    async def persist_run_state(
        self,
        run_id: str,
        *,
        status: str,
        session_status: str | None = None,
        stop_reason: str | None = None,
        ended: bool = False,
    ) -> None:
        """持久化 Run 状态，并在需要时同步会话状态和结束时间。"""
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

    async def mark_run_running(self, run_id: str, *, ensure_started_at: bool = False) -> DiscussionRun | None:
        """把 Run 切到 running，并确保 started_at / session.status 一致。"""
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return None
            run.status = "running"
            if ensure_started_at:
                run.started_at = run.started_at or datetime.now(timezone.utc)
            run.ended_at = None
            run.stop_reason = None
            session = await db.get(ChatSession, run.session_id)
            if session:
                session.status = "running"
            await db.commit()
            await db.refresh(run)
            return run

    async def update_current_round(self, run_id: str, round_no: int) -> None:
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return
            run.current_round = round_no
            await db.commit()

    async def save_report(
        self,
        run_id: str,
        *,
        title: str,
        summary_markdown: str,
        conclusion_json: dict[str, Any],
    ) -> FinalReport:
        """保存最终报告实体。"""
        async with SessionLocal() as db:
            report = FinalReport(
                run_id=run_id,
                title=title,
                summary_markdown=summary_markdown,
                conclusion_json=conclusion_json,
            )
            db.add(report)
            await db.commit()
            await db.refresh(report)
            return report

    async def create_tool_log(
        self,
        *,
        run_id: str,
        round_no: int,
        agent_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> None:
        """记录一次工具调用开始。"""
        async with SessionLocal() as db:
            db.add(
                ToolCallLog(
                    run_id=run_id,
                    round_no=round_no,
                    agent_id=agent_id,
                    call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_input_json=tool_input,
                    tool_output_json={},
                    status="started",
                )
            )
            await db.commit()

    async def complete_tool_log(self, *, run_id: str, tool_call_id: str, tool_output: dict[str, Any]) -> None:
        async with SessionLocal() as db:
            res = await db.execute(select(ToolCallLog).where(ToolCallLog.run_id == run_id, ToolCallLog.call_id == tool_call_id))
            row = res.scalars().first()
            if not row:
                return
            row.tool_output_json = tool_output
            row.status = "completed"
            row.ended_at = datetime.now(timezone.utc)
            await db.commit()

    async def fail_tool_log(self, *, run_id: str, tool_call_id: str, error_payload: dict[str, Any]) -> None:
        async with SessionLocal() as db:
            res = await db.execute(select(ToolCallLog).where(ToolCallLog.run_id == run_id, ToolCallLog.call_id == tool_call_id))
            row = res.scalars().first()
            if not row:
                return
            row.tool_output_json = error_payload
            row.status = "failed"
            row.ended_at = datetime.now(timezone.utc)
            await db.commit()

    async def is_terminal_run(self, run_id: str) -> bool:
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            return bool(run and run.status in {"finished", "failed", "stopped"})

    async def load_run(self, db: AsyncSession, run_id: str) -> DiscussionRun | None:
        """按运行时执行所需的关联关系完整装载一个 Run。"""
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
            )
            .where(DiscussionRun.id == run_id)
        )
        return res.scalar_one_or_none()

    async def load_agent(self, agent_id: str) -> AgentConfig | None:
        async with SessionLocal() as db:
            res = await db.execute(
                select(AgentConfig)
                .options(
                    selectinload(AgentConfig.model).selectinload(ModelConfig.provider),
                    selectinload(AgentConfig.tool_bindings).selectinload(AgentToolBinding.tool),
                    selectinload(AgentConfig.skill_bindings).selectinload(AgentSkillBinding.skill),
                    selectinload(AgentConfig.mcp_bindings).selectinload(AgentMCPBinding.mcp),
                )
                .where(AgentConfig.id == agent_id)
            )
            return res.scalar_one_or_none()

    async def load_session_for_reply(self, db: AsyncSession, session_id: str) -> ChatSession | None:
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

    async def sync_session_status(self, db: AsyncSession, session_id: str) -> None:
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

    async def list_runs_for_recovery(self) -> list[DiscussionRun]:
        async with SessionLocal() as db:
            res = await db.execute(
                select(DiscussionRun)
                .where(DiscussionRun.status.in_(["draft", "running", "paused"]))
                .order_by(DiscussionRun.created_at.asc())
            )
            return list(res.scalars().all())

    async def create_run(self, session_id: str, *, notify_feishu: bool) -> DiscussionRun:
        """为指定会话创建新的草稿 Run，并阻止并发活动 Run 共存。"""
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
            except Exception:
                await db.rollback()
                raise
            result = await db.execute(
                select(DiscussionRun)
                .options(selectinload(DiscussionRun.reports))
                .where(DiscussionRun.id == run.id)
            )
            return result.scalar_one()

    async def update_run_status(
        self,
        run_id: str,
        *,
        run_status: str | None = None,
        session_status: str | None = None,
        stop_reason: str | None = None,
        ended: bool = False,
    ) -> DiscussionRun | None:
        """按需更新 Run 状态、stop_reason、ended_at 和 session.status。"""
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return None
            if run_status is not None:
                run.status = run_status
            if stop_reason is not None:
                run.stop_reason = stop_reason
            if ended:
                run.ended_at = datetime.now(timezone.utc)
            if session_status is not None:
                session = await db.get(ChatSession, run.session_id)
                if session:
                    session.status = session_status
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

    async def delete_run_records(self, run_id: str) -> bool:
        """删除 Run 关联的报告、工具日志、事件计数器和主体记录。"""
        async with SessionLocal() as db:
            run = await db.get(DiscussionRun, run_id)
            if not run:
                return False
            session_id = run.session_id
            await db.execute(delete(FinalReport).where(FinalReport.run_id == run_id))
            await db.execute(delete(ToolCallLog).where(ToolCallLog.run_id == run_id))
            await db.execute(delete(DiscussionEvent).where(DiscussionEvent.run_id == run_id))
            await db.execute(delete(DiscussionEventCounter).where(DiscussionEventCounter.run_id == run_id))
            await db.execute(delete(DiscussionRun).where(DiscussionRun.id == run_id))
            await db.flush()
            await self.sync_session_status(db, session_id)
            await db.commit()
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
