from __future__ import annotations

import uuid
from typing import Any

from app.entities import FinalReport
from app.runtime_common import EventService


class RunExecutionNotifier:
    """把运行期状态变化翻译成统一事件格式。

    这样上层执行逻辑只需表达“发生了什么”，而不必关心具体事件名和 payload 结构。
    """

    def __init__(self, event_service: EventService) -> None:
        self.event_service = event_service

    async def publish_round_started(self, run_id: str, *, round_no: int) -> None:
        await self.event_service.publish(
            run_id,
            "run_status",
            round_no=round_no,
            payload={"status": "round_started", "round_no": round_no},
        )

    async def publish_paused(self, run_id: str, *, round_no: int, source: str) -> None:
        await self.event_service.publish(
            run_id,
            "run_status",
            round_no=round_no,
            payload={"status": "paused", "source": source},
        )

    async def publish_user_input(self, run_id: str, *, round_no: int, text: str, source: str, mark_important: bool) -> None:
        await self.event_service.publish(
            run_id,
            "user_input",
            round_no=round_no,
            payload={
                "text": text,
                "source": source,
                "metadata": {
                    "mark_important": mark_important,
                    "human_priority": "pinned" if mark_important else "normal",
                },
            },
        )

    async def publish_message_completed(
        self,
        run_id: str,
        *,
        round_no: int,
        agent_id: str,
        agent_name: str,
        text: str,
        metadata: dict[str, Any],
        message_id: str | None = None,
    ) -> None:
        await self.event_service.publish(
            run_id,
            "message_completed",
            round_no=round_no,
            agent_id=agent_id,
            payload={
                "message_id": message_id or uuid.uuid4().hex,
                "agent_name": agent_name,
                "role": "assistant",
                "text": text,
                "metadata": metadata,
            },
        )

    async def publish_moderator_decision(
        self,
        run_id: str,
        *,
        round_no: int,
        payload: dict[str, Any],
        structured_state: dict[str, Any],
    ) -> None:
        await self.event_service.publish(
            run_id,
            "run_status",
            round_no=round_no,
            payload={"status": "moderator_decision", **payload, "structured_state": structured_state},
        )

    async def publish_running(self, run_id: str) -> None:
        await self.event_service.publish(run_id, "run_status", payload={"status": "running"})

    async def publish_stopped(self, run_id: str, *, source: str) -> None:
        await self.event_service.publish(run_id, "run_status", payload={"status": "stopped", "source": source})

    async def publish_finished(self, run_id: str) -> None:
        await self.event_service.publish(run_id, "run_status", payload={"status": "finished"})

    async def publish_error(self, run_id: str, *, message: str) -> None:
        await self.event_service.publish(run_id, "error", payload={"message": message})

    async def publish_report_generated(self, run_id: str, *, report: FinalReport) -> None:
        await self.event_service.publish(
            run_id,
            "report_generated",
            payload={
                "report_id": report.id,
                "title": report.title,
                "summary_markdown": report.summary_markdown,
                "conclusion_json": report.conclusion_json,
            },
        )

    async def publish_tool_started(
        self,
        run_id: str,
        *,
        round_no: int,
        agent_id: str,
        tool_name: str,
        tool_call_id: str,
        tool_input: dict[str, Any],
    ) -> None:
        await self.event_service.publish(
            run_id,
            "tool_started",
            round_no=round_no,
            agent_id=agent_id,
            tool_name=tool_name,
            payload={"message_id": uuid.uuid4().hex, "call_id": tool_call_id, "input": tool_input},
        )

    async def publish_tool_completed(
        self,
        run_id: str,
        *,
        round_no: int,
        agent_id: str,
        tool_name: str,
        tool_call_id: str,
        output_chunk: list[dict[str, Any]],
    ) -> None:
        await self.event_service.publish(
            run_id,
            "tool_completed",
            round_no=round_no,
            agent_id=agent_id,
            tool_name=tool_name,
            payload={"message_id": uuid.uuid4().hex, "call_id": tool_call_id, "output": output_chunk},
        )

    async def publish_tool_failed(
        self,
        run_id: str,
        *,
        round_no: int,
        agent_id: str,
        tool_name: str,
        tool_call_id: str,
        tool_input: dict[str, Any],
        error_payload: dict[str, Any],
    ) -> None:
        await self.event_service.publish(
            run_id,
            "tool_failed",
            round_no=round_no,
            agent_id=agent_id,
            tool_name=tool_name,
            payload={"call_id": tool_call_id, "input": tool_input, **error_payload},
        )
