from __future__ import annotations

import asyncio
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


def wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.05, message: str = "condition not met") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError(message)


async def broker_roundtrip(broker: Any, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    queue = await broker.subscribe(run_id)
    try:
        await broker.publish(run_id, payload)
        return await asyncio.wait_for(queue.get(), timeout=1.0)
    finally:
        await broker.unsubscribe(run_id, queue)


def main() -> None:
    with TestClient(app) as client:
        broker = app.state.broker

        broker_run_id = f"broker-{uuid.uuid4().hex[:8]}"
        broker_payload = {
            "run_id": broker_run_id,
            "seq": 1,
            "event_type": "run_status",
            "payload": {"status": "running"},
        }
        received = asyncio.run(broker_roundtrip(broker, broker_run_id, broker_payload))
        assert received == broker_payload, received
        assert broker_run_id not in broker._subs or not broker._subs[broker_run_id], broker._subs.get(broker_run_id)
        print(f"[ok] broker roundtrip: run={broker_run_id}")

        ws_run_id = f"ws-{uuid.uuid4().hex[:8]}"
        ws_payload = {
            "run_id": ws_run_id,
            "seq": 7,
            "event_type": "message_completed",
            "payload": {"text": "hello websocket"},
        }
        with client.websocket_connect(f"/api/v1/ws/runs/{ws_run_id}") as websocket:
            wait_until(
                lambda: ws_run_id in broker._subs and len(broker._subs[ws_run_id]) == 1,
                message=f"websocket subscriber not registered: {broker._subs}",
            )
            queue = next(iter(broker._subs[ws_run_id]))
            queue.put_nowait(ws_payload)
            received_ws = websocket.receive_json()
            assert received_ws == ws_payload, received_ws
        wait_until(
            lambda: ws_run_id not in broker._subs or not broker._subs[ws_run_id],
            message=f"websocket subscriber not cleaned up: {broker._subs.get(ws_run_id)}",
        )
        print(f"[ok] websocket bridge: run={ws_run_id}")

        print("langgraph realtime test passed")


if __name__ == "__main__":
    main()
