from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.entities import AgentConfig  # noqa: E402
from app.main import app  # noqa: E402


async def _unset_moderator(agent_id: str) -> None:
    async with SessionLocal() as db:
        agent = await db.get(AgentConfig, agent_id)
        assert agent is not None
        agent.is_moderator = False
        await db.commit()


def main() -> None:
    unique = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
        provider = client.post(
            "/api/v1/providers",
            json={"provider_type": "mock", "name": f"moderator-test-provider-{unique}", "api_key": None, "base_url": None, "organization": None, "extra_config_json": {}},
        )
        assert provider.status_code == 201, provider.text

        model = client.post(
            "/api/v1/models",
            json={
                "provider_id": provider.json()["id"],
                "model_name": f"mock-gpt-{unique}",
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
                "name": f"moderator-test-participant-{unique}",
                "role": "Participant",
                "persona": "Participant",
                "system_prompt": "请给出简洁分析。",
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

        observer = client.post(
            "/api/v1/agents",
            json={
                "name": f"moderator-test-observer-{unique}",
                "role": "Observer",
                "persona": "Observer",
                "system_prompt": "请补充观察结论。",
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
        assert observer.status_code == 201, observer.text

        moderator = client.post(
            "/api/v1/agents",
            json={
                "name": f"moderator-test-moderator-{unique}",
                "role": "Moderator",
                "persona": "Moderator",
                "system_prompt": "你负责主持讨论。",
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

        no_moderator_session = client.post(
            "/api/v1/chat-sessions",
            json={
                "name": f"moderator-test-no-mod-{unique}",
                "topic": "验证无 moderator 时禁止创建。",
                "max_rounds": 2,
                "status": "draft",
                "agent_ids": [participant.json()["id"], observer.json()["id"]],
                "feishu_enabled": False,
            },
        )
        assert no_moderator_session.status_code == 400, no_moderator_session.text
        assert "Moderator" in no_moderator_session.text

        valid_session = client.post(
            "/api/v1/chat-sessions",
            json={
                "name": f"moderator-test-valid-{unique}",
                "topic": "验证 moderator 校验。",
                "max_rounds": 2,
                "status": "draft",
                "agent_ids": [participant.json()["id"], moderator.json()["id"]],
                "feishu_enabled": False,
            },
        )
        assert valid_session.status_code == 201, valid_session.text
        session_id = valid_session.json()["id"]

        invalid_update = client.put(
            f"/api/v1/chat-sessions/{session_id}",
            json={"agent_ids": [participant.json()["id"], observer.json()["id"]]},
        )
        assert invalid_update.status_code == 400, invalid_update.text
        assert "Moderator" in invalid_update.text

        asyncio.run(_unset_moderator(moderator.json()["id"]))
        invalid_start = client.post(f"/api/v1/chat-sessions/{session_id}/start", json={"notify_feishu": False})
        assert invalid_start.status_code == 400, invalid_start.text
        assert "Moderator" in invalid_start.text

    print("langgraph moderator validation test passed")


if __name__ == "__main__":
    main()
