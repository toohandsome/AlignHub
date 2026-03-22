from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APP_CLEANUP_RUN_WORKSPACE_ON_FINISH", "false")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def wait_run(client: TestClient, run_id: str, *, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = client.get(f"/api/v1/runs/{run_id}").json()
        if last["status"] in {"finished", "failed", "stopped"}:
            return last
        time.sleep(0.2)
    raise TimeoutError(f"Run {run_id} did not finish in time: {last}")


def wait_until(predicate, *, timeout: float = 10.0, interval: float = 0.2, message: str = "condition not met") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError(message)


def create_session(client: TestClient, agent_ids: list[str], *, name: str, topic: str, feishu_enabled: bool = False) -> dict[str, Any]:
    feishu_suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/v1/chat-sessions",
        json={
            "name": name,
            "topic": topic,
            "max_rounds": 6,
            "status": "draft",
            "agent_ids": agent_ids,
            "feishu_enabled": feishu_enabled,
            "feishu_chat_id": f"oc_test_chat_{feishu_suffix}" if feishu_enabled else None,
            "feishu_topic_root_id": f"om_test_topic_root_{feishu_suffix}" if feishu_enabled else None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def payloads(events: list[dict[str, Any]]) -> list[tuple[str, str | None, str | None]]:
    return [
        (
            event["event_type"],
            (event.get("payload_json") or {}).get("status"),
            (event.get("payload_json") or {}).get("text"),
        )
        for event in events
    ]


def main() -> None:
    with TestClient(app) as client:
        bootstrap = client.post("/api/v1/demo/bootstrap")
        assert bootstrap.status_code == 200, bootstrap.text
        agent_ids = bootstrap.json()["agent_ids"]

        tool_session = create_session(
            client,
            agent_ids,
            name=f"LG smoke {uuid.uuid4().hex[:8]}",
            topic="mock provider tool smoke",
        )
        tool_run_id = client.post(
            f"/api/v1/chat-sessions/{tool_session['id']}/start",
            json={"notify_feishu": False},
        ).json()["id"]
        tool_final = wait_run(client, tool_run_id)
        assert tool_final["status"] == "finished", tool_final
        tool_events = client.get(f"/api/v1/runs/{tool_run_id}/events").json()
        tool_logs = client.get(f"/api/v1/runs/{tool_run_id}/tool-logs").json()
        assert any(item["event_type"] == "tool_started" for item in tool_events), tool_events
        assert any(item["event_type"] == "tool_completed" for item in tool_events), tool_events
        assert len(tool_logs) >= 2, tool_logs
        print(f"[ok] tool smoke: run={tool_run_id} tool_logs={len(tool_logs)}")

        pause_session = create_session(
            client,
            agent_ids,
            name=f"LG pause {uuid.uuid4().hex[:8]}",
            topic="pause resume smoke",
        )
        pause_run_id = client.post(
            f"/api/v1/chat-sessions/{pause_session['id']}/start",
            json={"notify_feishu": False},
        ).json()["id"]
        time.sleep(0.25)
        assert client.post(
            f"/api/v1/runs/{pause_run_id}/pause",
            json={"message": "pause from ui", "source": "itest"},
        ).status_code == 200
        time.sleep(0.6)
        pause_events = client.get(f"/api/v1/runs/{pause_run_id}/events").json()
        pause_rows = payloads(pause_events)
        paused_idx = next(i for i, row in enumerate(pause_rows) if row[0] == "run_status" and row[1] == "paused")
        pause_input_idx = next(i for i, row in enumerate(pause_rows) if row[0] == "user_input" and row[2] == "pause from ui")
        assert pause_input_idx > paused_idx, pause_rows
        assert client.post(
            f"/api/v1/runs/{pause_run_id}/user-input",
            json={"message": "more input", "source": "itest", "pause": False},
        ).status_code == 200
        assert client.post(
            f"/api/v1/runs/{pause_run_id}/resume",
            json={"message": "continue now", "source": "itest"},
        ).status_code == 200
        pause_final = wait_run(client, pause_run_id)
        assert pause_final["status"] == "finished", pause_final
        pause_rows = payloads(client.get(f"/api/v1/runs/{pause_run_id}/events").json())
        assert any(row[0] == "run_status" and row[1] == "resumed" for row in pause_rows), pause_rows
        assert any(row[0] == "user_input" and row[2] == "more input" for row in pause_rows), pause_rows
        assert any(row[0] == "user_input" and row[2] == "continue now" for row in pause_rows), pause_rows
        print(f"[ok] pause/resume: run={pause_run_id}")

        input_pause_session = create_session(
            client,
            agent_ids,
            name=f"LG inputpause {uuid.uuid4().hex[:8]}",
            topic="running user input pause true",
        )
        input_pause_run_id = client.post(
            f"/api/v1/chat-sessions/{input_pause_session['id']}/start",
            json={"notify_feishu": False},
        ).json()["id"]
        time.sleep(0.25)
        assert client.post(
            f"/api/v1/runs/{input_pause_run_id}/user-input",
            json={"message": "running pause input", "source": "itest", "pause": True},
        ).status_code == 200
        time.sleep(0.6)
        input_pause_rows = payloads(client.get(f"/api/v1/runs/{input_pause_run_id}/events").json())
        assert any(row[0] == "run_status" and row[1] == "paused" for row in input_pause_rows), input_pause_rows
        assert any(row[0] == "user_input" and row[2] == "running pause input" for row in input_pause_rows), input_pause_rows
        assert client.post(
            f"/api/v1/runs/{input_pause_run_id}/resume",
            json={"source": "itest"},
        ).status_code == 200
        input_pause_final = wait_run(client, input_pause_run_id)
        assert input_pause_final["status"] == "finished", input_pause_final
        print(f"[ok] running user-input pause=true: run={input_pause_run_id}")

        sent_messages: list[dict[str, Any]] = []

        async def fake_send_message(
            chat_id: str,
            *,
            title: str,
            body: str,
            agent_id: str | None = None,
            source_kind: str = "host",
            reply_to_message_id: str | None = None,
        ) -> dict[str, Any]:
            sent_messages.append(
                {
                    "chat_id": chat_id,
                    "title": title,
                    "body": body,
                    "agent_id": agent_id,
                    "source_kind": source_kind,
                    "reply_to_message_id": reply_to_message_id,
                }
            )
            return {"message_id": f"om_fake_{len(sent_messages)}"}

        app.state.feishu_bridge._messaging.send_message = fake_send_message
        feishu_session = create_session(
            client,
            agent_ids,
            name=f"LG feishu {uuid.uuid4().hex[:8]}",
            topic="feishu bridge smoke",
            feishu_enabled=True,
        )
        feishu_run_id = client.post(
            f"/api/v1/chat-sessions/{feishu_session['id']}/start",
            json={"notify_feishu": True},
        ).json()["id"]
        time.sleep(0.25)
        client.post(
            f"/api/v1/runs/{feishu_run_id}/pause",
            json={"message": "pause from ui", "source": "itest"},
        )
        time.sleep(0.5)
        client.post(
            f"/api/v1/runs/{feishu_run_id}/user-input",
            json={"message": "more input", "source": "itest", "pause": False},
        )
        client.post(
            f"/api/v1/runs/{feishu_run_id}/resume",
            json={"message": "continue now", "source": "itest"},
        )
        feishu_final = wait_run(client, feishu_run_id)
        assert feishu_final["status"] == "finished", feishu_final
        wait_until(
            lambda: any("Final Report" in item["title"] or "最终报告" in item["title"] for item in sent_messages),
            timeout=10.0,
            message=f"Feishu final report not captured: {sent_messages}",
        )
        joined = "\n".join(f"{item['title']} => {item['body']}" for item in sent_messages)
        assert "讨论已暂停" in joined, joined
        assert "用户补充信息" in joined, joined
        assert "讨论已恢复" in joined or "讨论已继续" in joined, joined
        assert "Final Report" in joined or "最终报告" in joined, joined
        print(f"[ok] feishu bridge: run={feishu_run_id} messages={len(sent_messages)}")

        print("langgraph smoke test passed")


if __name__ == "__main__":
    main()
