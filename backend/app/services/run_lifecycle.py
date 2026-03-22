from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.types import Command
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.services.context_retrieval import purge_run_chunks
from app.services.run_persistence import RunPersistenceService
from app.services.workspace import cleanup_run_workspace_async

logger = logging.getLogger(__name__)


class RunLifecycleService:
    def __init__(self, *, event_service: Any, engine: Any, persistence: RunPersistenceService) -> None:
        self.event_service = event_service
        self.engine = engine
        self.persistence = persistence
        self._tasks: dict[str, asyncio.Task] = {}
        self._session_start_locks: dict[str, asyncio.Lock] = {}

    def session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_start_locks:
            self._session_start_locks[session_id] = asyncio.Lock()
        return self._session_start_locks[session_id]

    def track_task(self, run_id: str, task: asyncio.Task) -> None:
        self._tasks[run_id] = task

        def _cleanup(_task: asyncio.Task) -> None:
            self._tasks.pop(run_id, None)

        task.add_done_callback(_cleanup)

    async def startup(self) -> None:
        await self.engine.startup()
        from app.core import settings

        if settings.langgraph_recover_active_runs:
            await self.recover_active_runs()

    async def shutdown(self) -> None:
        self.engine._shutdown_requested = True
        for run_id, task in list(self._tasks.items()):
            if task.done():
                continue
            task.cancel()
        for run_id, task in list(self._tasks.items()):
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Run %s raised during shutdown: %s", run_id, exc)
        self._tasks.clear()
        await self.engine.shutdown()

    async def recover_active_runs(self) -> list[str]:
        recovered: list[str] = []
        runs = await self.persistence.list_runs_for_recovery()
        for run in runs:
            await self.engine.restore_control(run.id, dict(run.control_state_json or {}))
            graph_state = await self.engine.graph_state(run.id)
            has_checkpoint = getattr(graph_state, "created_at", None) is not None
            has_interrupt = bool(getattr(graph_state, "interrupts", ()) or ())
            has_next = bool(getattr(graph_state, "next", ()) or ())

            if run.status == "paused":
                recovered.append(run.id)
                continue

            if run.status in {"draft", "running"}:
                if has_interrupt:
                    self.track_task(
                        run.id,
                        asyncio.create_task(self.engine.execute(run.id, command=Command(resume={"source": "recovery"}))),
                    )
                elif has_checkpoint and has_next:
                    self.track_task(run.id, asyncio.create_task(self.engine.execute(run.id, continue_from_checkpoint=True)))
                else:
                    self.track_task(run.id, asyncio.create_task(self.engine.execute(run.id)))
                recovered.append(run.id)

        if recovered:
            logger.info("Recovered LangGraph runs on startup: %s", recovered)
        return recovered

    async def start(self, session_id: str, *, notify_feishu: bool = True) -> Any:
        await self.engine.startup()
        async with self.session_lock(session_id):
            try:
                run = await self.persistence.create_run(session_id, notify_feishu=notify_feishu)
            except IntegrityError as exc:
                raise ValueError("Chat session already has an active run") from exc
        self.track_task(run.id, asyncio.create_task(self.engine.execute(run.id)))
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

        run = await self.persistence.get_run(run_id)
        if not run:
            self.engine.clear_control(run_id)
            return
        if run.status in {"finished", "failed", "stopped"}:
            return
        updated = await self.persistence.update_run_status(
            run_id,
            run_status="stopped",
            session_status="stopped",
            stop_reason="Stopped by user",
            ended=True,
        )
        if updated:
            await self.event_service.publish(run_id, "run_status", payload={"status": "stopped", "source": source})
        self._tasks.pop(run_id, None)
        await self.engine.clear_persisted_control_state(run_id)
        self.engine.clear_control(run_id)
        await cleanup_run_workspace_async(run_id)

    async def pause(self, run_id: str, *, message: str | None = None, source: str = "user", mark_important: bool = False) -> Any | None:
        run = await self.persistence.get_run(run_id)
        if not run:
            return None
        if run.status in {"finished", "failed", "stopped"}:
            raise ValueError("Run is no longer active")
        control = self.engine.control(run_id)
        became_paused = await control.request_pause(message=message, source=source, mark_important=mark_important)
        run = await self.persistence.get_run(run_id)
        if not run:
            self.engine.clear_control(run_id)
            return None
        if run.status in {"finished", "failed", "stopped"}:
            self.engine.clear_control(run_id)
            raise ValueError("Run is no longer active")
        if became_paused and run.status != "paused":
            run = await self.persistence.update_run_status(run_id, run_status="paused", session_status="paused")
        return run

    async def resume(self, run_id: str, *, message: str | None = None, source: str = "user", mark_important: bool = False) -> Any | None:
        run = await self.persistence.get_run(run_id)
        if not run:
            return None
        if run.status in {"finished", "failed", "stopped"}:
            raise ValueError("Run is no longer active")
        control = self.engine.control(run_id)
        await control.resume(message=message, source=source, mark_important=mark_important)
        task = self._tasks.get(run_id)
        if not task or task.done():
            graph_state = await self.engine.graph_state(run_id)
            has_checkpoint = getattr(graph_state, "created_at", None) is not None
            has_interrupt = bool(getattr(graph_state, "interrupts", ()) or ())
            has_next = bool(getattr(graph_state, "next", ()) or ())
            if has_interrupt:
                task = asyncio.create_task(self.engine.execute(run_id, command=Command(resume={"source": source})))
            elif has_checkpoint and has_next:
                task = asyncio.create_task(self.engine.execute(run_id, continue_from_checkpoint=True))
            else:
                task = asyncio.create_task(self.engine.execute(run_id))
            self.track_task(run_id, task)
        run = await self.persistence.get_run(run_id)
        if not run:
            self.engine.clear_control(run_id)
            return None
        if run.status in {"finished", "failed", "stopped"}:
            self.engine.clear_control(run_id)
            raise ValueError("Run is no longer active")
        if run.status == "paused":
            run = await self.persistence.update_run_status(run_id, run_status="running", session_status="running")
        await self.event_service.publish(
            run_id,
            "run_status",
            round_no=(run.current_round if run else 0),
            payload={"status": "resumed", "source": source},
        )
        return run

    async def inject_user_input(self, run_id: str, *, message: str, source: str = "user", pause: bool = False, mark_important: bool = False) -> Any | None:
        if not (message or "").strip():
            raise ValueError("Message is required")
        run = await self.persistence.get_run(run_id)
        if not run:
            return None
        if run.status in {"finished", "failed", "stopped"}:
            raise ValueError("Run is no longer active")
        control = self.engine.control(run_id)
        await control.add_input(message=message, source=source, pause=pause, mark_important=mark_important)
        run = await self.persistence.get_run(run_id)
        if not run:
            self.engine.clear_control(run_id)
            return None
        if run.status in {"finished", "failed", "stopped"}:
            self.engine.clear_control(run_id)
            raise ValueError("Run is no longer active")
        if pause and run.status not in {"finished", "failed", "stopped", "paused"}:
            run = await self.persistence.update_run_status(run_id, run_status="paused", session_status="paused")
        return run

    async def delete_run(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task and not task.done():
            await self.stop(run_id, source="delete")

        try:
            deleted = await self.persistence.delete_run_records(run_id)
        except DatabaseError:
            raise
        if not deleted:
            await cleanup_run_workspace_async(run_id)
            self.engine.clear_control(run_id)
            return False
        self._tasks.pop(run_id, None)
        await self.engine.clear_persisted_control_state(run_id)
        self.engine.clear_control(run_id)
        await asyncio.to_thread(purge_run_chunks, run_id)
        await cleanup_run_workspace_async(run_id)
        return True

    async def get_run(self, run_id: str) -> Any | None:
        return await self.persistence.get_run(run_id)

    async def find_active_run_for_session(self, session_id: str) -> Any | None:
        return await self.persistence.find_active_run_for_session(session_id)

    async def list_runs(self, *, session_id: str | None = None) -> list[Any]:
        return await self.persistence.list_runs(session_id=session_id)

    async def list_events(self, run_id: str) -> list[Any]:
        return await self.persistence.list_events(run_id)

    async def get_report(self, run_id: str) -> Any | None:
        return await self.persistence.get_report(run_id)

    async def list_tool_logs(self, run_id: str) -> list[Any]:
        return await self.persistence.list_tool_logs(run_id)

    async def ask_agent_in_session(self, session_id: str, agent_name: str, question: str) -> dict[str, Any]:
        return await self.engine.ask_agent_in_session(session_id, agent_name, question)
