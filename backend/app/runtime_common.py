from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import RealtimeBroker
from app.db import SessionLocal
from app.entities import DiscussionEvent, FinalReport

logger = logging.getLogger(__name__)


class ModeratorDecision(BaseModel):
    finished: bool = Field(description="Whether the discussion should finish")
    reason: str | None = Field(default=None)
    next_focus: str | None = Field(default=None)
    key_points: list[str] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    candidate_options: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class StructuredStateItem(BaseModel):
    value: str = Field(min_length=1)
    status: str = Field(default="active")
    created_round: int = Field(default=0, ge=0)
    last_seen_round: int = Field(default=0, ge=0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    support_count: int = Field(default=1, ge=1)
    source: str = Field(default="moderator")


class StatePatchProposal(BaseModel):
    id: str = Field(min_length=1)
    round_no: int = Field(ge=0)
    agent_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    source_message_id: str | None = Field(default=None)
    target_field: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    value: str = Field(min_length=1)
    reason: str | None = Field(default=None)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    status: str = Field(default="pending")
    risk_level: str = Field(default="medium")


@dataclass
class PendingUserInput:
    text: str
    source: str = "user"
    mark_important: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    announced: bool = False


class RunControlState:
    def __init__(self, *, on_change: Callable[[dict[str, Any]], Awaitable[None]] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self.pause_requested = False
        self.pending_inputs: list[PendingUserInput] = []
        self._last_pause_request: tuple[str, str] | None = None
        self._pause_source: str | None = None
        self._resume_source: str | None = None
        self._stop_source: str | None = None
        self._on_change = on_change

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self._snapshot_unlocked()

    async def restore_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        snapshot = dict(snapshot or {})
        async with self._lock:
            self.pause_requested = bool(snapshot.get("pause_requested"))
            self.pending_inputs = []
            for item in list(snapshot.get("pending_inputs") or []):
                created_at_raw = item.get("created_at")
                created_at = datetime.now(timezone.utc)
                if isinstance(created_at_raw, str):
                    try:
                        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
                    except ValueError:
                        created_at = datetime.now(timezone.utc)
                self.pending_inputs.append(
                    PendingUserInput(
                        text=str(item.get("text") or ""),
                        source=str(item.get("source") or "user"),
                        mark_important=bool(item.get("mark_important")),
                        created_at=created_at,
                        announced=bool(item.get("announced")),
                    )
                )
            last_pause = snapshot.get("last_pause_request")
            self._last_pause_request = (str(last_pause[0]), str(last_pause[1])) if isinstance(last_pause, list) and len(last_pause) == 2 else None
            self._pause_source = str(snapshot.get("pause_source")) if snapshot.get("pause_source") else None
            self._resume_source = str(snapshot.get("resume_source")) if snapshot.get("resume_source") else None
            self._stop_source = str(snapshot.get("stop_source")) if snapshot.get("stop_source") else None
            self._resume_event.clear() if self.pause_requested else self._resume_event.set()

    async def clear_runtime_state(self) -> None:
        async with self._lock:
            self.pause_requested = False
            self.pending_inputs.clear()
            self._last_pause_request = None
            self._pause_source = None
            self._resume_source = None
            self._stop_source = None
            self._resume_event.set()
        await self._notify_changed()

    async def request_pause(self, *, message: str | None = None, source: str = "user", mark_important: bool = False) -> bool:
        became_paused = False
        async with self._lock:
            normalized = (message or "").strip()
            if normalized:
                signature = (source, f"{normalized}|important={int(mark_important)}")
                if self._last_pause_request != signature:
                    self.pending_inputs.append(PendingUserInput(text=normalized, source=source, mark_important=mark_important))
                    self._last_pause_request = signature
            if not self.pause_requested or self._resume_event.is_set():
                became_paused = True
                self._pause_source = source
            self.pause_requested = True
            self._resume_event.clear()
        await self._notify_changed()
        return became_paused

    async def add_input(self, *, message: str, source: str = "user", pause: bool = False, mark_important: bool = False) -> None:
        text = (message or "").strip()
        if not text:
            return
        if pause:
            await self.request_pause(message=text, source=source, mark_important=mark_important)
            return
        async with self._lock:
            self.pending_inputs.append(PendingUserInput(text=text, source=source, mark_important=mark_important))
            self._last_pause_request = None
        await self._notify_changed()

    async def resume(self, *, message: str | None = None, source: str = "user", mark_important: bool = False) -> None:
        async with self._lock:
            if message and message.strip():
                self.pending_inputs.append(PendingUserInput(text=message.strip(), source=source, mark_important=mark_important))
            self.pause_requested = False
            self._resume_event.set()
            self._last_pause_request = None
            self._resume_source = source
        await self._notify_changed()

    async def request_stop(self, *, source: str = "user") -> None:
        async with self._lock:
            self._stop_source = source
        await self._notify_changed()

    async def wait_until_resumed(self) -> None:
        await self._resume_event.wait()

    async def drain_inputs(self) -> list[PendingUserInput]:
        async with self._lock:
            pending = list(self.pending_inputs)
            self.pending_inputs.clear()
        await self._notify_changed()
        return pending

    async def mark_inputs_announced(self) -> list[PendingUserInput]:
        async with self._lock:
            pending = [item for item in self.pending_inputs if not item.announced]
            for item in pending:
                item.announced = True
            announced = list(pending)
        await self._notify_changed()
        return announced

    async def is_paused(self) -> bool:
        async with self._lock:
            return self.pause_requested or not self._resume_event.is_set()

    async def consume_pause_source(self) -> str | None:
        async with self._lock:
            source = self._pause_source
            self._pause_source = None
        await self._notify_changed()
        return source

    async def consume_resume_source(self) -> str | None:
        async with self._lock:
            source = self._resume_source
            self._resume_source = None
        await self._notify_changed()
        return source

    async def consume_stop_source(self, default: str | None = None) -> str | None:
        async with self._lock:
            source = self._stop_source or default
            self._stop_source = None
        await self._notify_changed()
        return source

    def _snapshot_unlocked(self) -> dict[str, Any]:
        return {
            "pause_requested": self.pause_requested,
            "pending_inputs": [
                {
                    "text": item.text,
                    "source": item.source,
                    "mark_important": item.mark_important,
                    "created_at": item.created_at.isoformat(),
                    "announced": item.announced,
                }
                for item in self.pending_inputs
            ],
            "last_pause_request": list(self._last_pause_request) if self._last_pause_request else None,
            "pause_source": self._pause_source,
            "resume_source": self._resume_source,
            "stop_source": self._stop_source,
        }

    async def _notify_changed(self) -> None:
        if self._on_change is None:
            return
        snapshot = await self.snapshot()
        try:
            await self._on_change(snapshot)
        except Exception as exc:
            logger.warning("Failed to persist run control state: %s", exc)


@dataclass
class _EventWriteRequest:
    run_id: str
    event_type: str
    round_no: int = 0
    agent_id: str | None = None
    tool_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    result_future: asyncio.Future[dict[str, Any]] | None = None


class EventService:
    def __init__(self, broker: RealtimeBroker) -> None:
        self.broker = broker
        self._listeners: list[Callable[[dict[str, Any]], Any]] = []
        self._queue: asyncio.Queue[_EventWriteRequest | None] | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()

    def register_listener(self, listener: Callable[[dict[str, Any]], Any]) -> None:
        self._listeners.append(listener)

    async def startup(self) -> None:
        async with self._lifecycle_lock:
            if self._writer_task and not self._writer_task.done():
                return
            self._queue = asyncio.Queue()
            self._writer_task = asyncio.create_task(self._writer_loop())

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            queue = self._queue
            task = self._writer_task
            self._queue = None
            self._writer_task = None
        if queue is None or task is None:
            return
        await queue.put(None)
        await task

    async def _ensure_started(self) -> None:
        if self._writer_task is None or self._writer_task.done():
            await self.startup()

    async def _next_event_seq(self, db: AsyncSession, run_id: str) -> int:
        result = await db.execute(
            text(
                """
                INSERT INTO discussion_event_counters(run_id, next_seq)
                VALUES (:run_id, 2)
                ON CONFLICT(run_id) DO UPDATE
                SET next_seq = discussion_event_counters.next_seq + 1
                RETURNING next_seq - 1 AS seq
                """
            ),
            {"run_id": run_id},
        )
        return int(result.scalar_one())

    async def _writer_loop(self) -> None:
        if self._queue is None:
            return
        stop_after_batch = False
        while True:
            request = await self._queue.get()
            if request is None:
                return
            batch = [request]
            await asyncio.sleep(0)
            while len(batch) < 100:
                try:
                    next_item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if next_item is None:
                    stop_after_batch = True
                    break
                batch.append(next_item)
            await self._persist_batch(batch)
            if stop_after_batch:
                return

    async def _persist_batch(self, batch: list[_EventWriteRequest]) -> None:
        rows: list[tuple[_EventWriteRequest, DiscussionEvent, int]] = []
        try:
            async with SessionLocal() as db:
                for request in batch:
                    seq = await self._next_event_seq(db, request.run_id)
                    row = DiscussionEvent(
                        run_id=request.run_id,
                        seq=seq,
                        round_no=request.round_no,
                        event_type=request.event_type,
                        agent_id=request.agent_id,
                        tool_name=request.tool_name,
                        payload_json=dict(request.payload or {}),
                    )
                    db.add(row)
                    rows.append((request, row, seq))
                await db.flush()
                events = [
                    {
                        "id": row.id,
                        "run_id": request.run_id,
                        "seq": seq,
                        "round_no": request.round_no,
                        "event_type": request.event_type,
                        "agent_id": request.agent_id,
                        "tool_name": request.tool_name,
                        "payload": dict(request.payload or {}),
                        "created_at": (row.created_at or datetime.now(timezone.utc)).isoformat(),
                    }
                    for request, row, seq in rows
                ]
                await db.commit()
        except Exception as exc:
            logger.exception("Failed to persist event batch of size %s", len(batch))
            for request in batch:
                future = request.result_future
                if future and not future.done():
                    future.set_exception(exc)
            return

        for request, event in zip(batch, events, strict=True):
            future = request.result_future
            if future and not future.done():
                future.set_result(event)

    async def _dispatch_event(self, event: dict[str, Any]) -> None:
        await self.broker.publish(event["run_id"], event)
        for listener in self._listeners:
            try:
                result = listener(dict(event))
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    task.add_done_callback(self._log_listener_exception)
            except Exception as exc:
                logger.warning("Event listener failed before scheduling: %s", exc)

    @staticmethod
    def _log_listener_exception(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except Exception as exc:
            logger.warning("Event listener task failed: %s", exc)

    async def publish(
        self,
        run_id: str,
        event_type: str,
        *,
        round_no: int = 0,
        agent_id: str | None = None,
        tool_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        await self._ensure_started()
        if self._queue is None:
            raise RuntimeError("EventService queue is not initialized")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        await self._queue.put(
            _EventWriteRequest(
                run_id=run_id,
                event_type=event_type,
                round_no=round_no,
                agent_id=agent_id,
                tool_name=tool_name,
                payload=payload,
                result_future=future,
            )
        )
        event = await future
        await self._dispatch_event(event)
        return event

    async def save_report(self, run_id: str, title: str, summary_markdown: str, conclusion_json: dict[str, Any]) -> FinalReport:
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
