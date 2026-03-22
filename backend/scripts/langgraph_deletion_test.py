from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.entities import ChatSession, ChatSessionAgent, DiscussionEvent, DiscussionEventCounter, DiscussionRun, FinalReport, ToolCallLog  # noqa: E402
from app.main import app  # noqa: E402


def _wait_run(client: TestClient, run_id: str, *, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/v1/runs/{run_id}").json()
        if payload["status"] in {"finished", "failed", "stopped"}:
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"Run {run_id} did not finish in time")


async def _assert_session_deleted(session_id: str, run_id: str) -> None:
    async with SessionLocal() as db:
        assert await db.get(ChatSession, session_id) is None
        assert await db.get(DiscussionRun, run_id) is None

        for model, column, value in [
            (ChatSessionAgent, ChatSessionAgent.session_id, session_id),
            (DiscussionEvent, DiscussionEvent.run_id, run_id),
            (DiscussionEventCounter, DiscussionEventCounter.run_id, run_id),
            (FinalReport, FinalReport.run_id, run_id),
            (ToolCallLog, ToolCallLog.run_id, run_id),
        ]:
            rows = (await db.execute(select(model).where(column == value))).scalars().all()
            assert not rows, f"{model.__tablename__} still contains rows for {value}"


def main() -> None:
    unique = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
        provider = client.post(
            "/api/v1/providers",
            json={"provider_type": "mock", "name": f"delete-test-provider-{unique}", "api_key": None, "base_url": None, "organization": None, "extra_config_json": {}},
        )
        assert provider.status_code == 201, provider.text
        provider_id = provider.json()["id"]

        model = client.post(
            "/api/v1/models",
            json={
                "provider_id": provider_id,
                "model_name": "mock-gpt",
                "temperature": 0.2,
                "max_tokens": 128,
                "stream_enabled": False,
                "formatter_type": "auto",
                "extra_config_json": {},
            },
        )
        assert model.status_code == 201, model.text
        model_id = model.json()["id"]

        participant = client.post(
            "/api/v1/agents",
            json={
                "name": "delete-test-participant",
                "name": f"delete-test-participant-{unique}",
                "role": "Participant",
                "persona": "Participant",
                "system_prompt": "请给出简洁可执行的分析。",
                "model_id": model_id,
                "memory_strategy": "in_memory",
                "max_steps": 4,
                "is_moderator": False,
                "extra_config_json": {},
                "tool_names": [],
                "skill_ids": [],
                "mcp_ids": [],
            },
        )
        assert participant.status_code == 201, participant.text

        moderator = client.post(
            "/api/v1/agents",
            json={
                "name": f"delete-test-moderator-{unique}",
                "role": "Moderator",
                "persona": "Moderator",
                "system_prompt": "你负责主持讨论并判断何时结束。",
                "model_id": model_id,
                "memory_strategy": "in_memory",
                "max_steps": 4,
                "is_moderator": True,
                "extra_config_json": {},
                "tool_names": [],
                "skill_ids": [],
                "mcp_ids": [],
            },
        )
        assert moderator.status_code == 201, moderator.text

        session = client.post(
            "/api/v1/chat-sessions",
            json={
                "name": f"delete-test-session-{unique}",
                "topic": "验证删除会话时是否能级联清理 run、事件与报告。",
                "max_rounds": 2,
                "status": "draft",
                "agent_ids": [participant.json()["id"], moderator.json()["id"]],
                "feishu_enabled": False,
            },
        )
        assert session.status_code == 201, session.text
        session_id = session.json()["id"]

        start = client.post(f"/api/v1/chat-sessions/{session_id}/start", json={"notify_feishu": False})
        assert start.status_code == 200, start.text
        run_id = start.json()["id"]
        final = _wait_run(client, run_id)
        assert final["status"] == "finished", final

        deleted = client.delete(f"/api/v1/chat-sessions/{session_id}")
        assert deleted.status_code == 204, deleted.text

        assert client.get(f"/api/v1/chat-sessions/{session_id}").status_code == 404
        assert client.get(f"/api/v1/runs/{run_id}").status_code == 404
        asyncio.run(_assert_session_deleted(session_id, run_id))

    print("langgraph deletion test passed")


if __name__ == "__main__":
    main()
