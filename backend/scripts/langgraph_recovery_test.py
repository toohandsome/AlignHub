from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _base_env(temp_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["APP_DATABASE_URL"] = _sqlite_url(temp_root / "recovery.db")
    env["APP_LANGGRAPH_CHECKPOINT_PATH"] = str((temp_root / "langgraph_checkpoints.sqlite").resolve())
    env["APP_ARTIFACT_ROOT"] = str((temp_root / "artifacts").resolve())
    env["APP_WORKSPACE_ROOT"] = str(REPO_ROOT.resolve())
    env["APP_CLEANUP_RUN_WORKSPACE_ON_FINISH"] = "false"
    env["APP_LANGGRAPH_MOCK_RESPONSE_DELAY_MS"] = "400"
    return env


def _run_subprocess(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(Path(__file__).resolve()), *args]
    return subprocess.run(command, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True, check=True)


def _wait_run(client: Any, run_id: str, *, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = client.get(f"/api/v1/runs/{run_id}").json()
        if last["status"] in {"finished", "failed", "stopped"}:
            return last
        time.sleep(0.2)
    raise TimeoutError(f"Run {run_id} did not finish in time: {last}")


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _create_unique_session(client: Any, agent_ids: list[str], topic: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/chat-sessions",
        json={
            "name": f"LG recovery {uuid.uuid4().hex[:8]}",
            "topic": topic,
            "max_rounds": 6,
            "status": "draft",
            "agent_ids": agent_ids,
            "feishu_enabled": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def phase_setup_paused(state_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        bootstrap = client.post("/api/v1/demo/bootstrap").json()
        session = _create_unique_session(client, bootstrap["agent_ids"], "paused recovery smoke")
        run_id = client.post(
            f"/api/v1/chat-sessions/{session['id']}/start",
            json={"notify_feishu": False},
        ).json()["id"]
        time.sleep(0.25)
        pause = client.post(
            f"/api/v1/runs/{run_id}/pause",
            json={"message": "pause before restart", "source": "itest"},
        )
        assert pause.status_code == 200, pause.text
        deadline = time.time() + 10
        while time.time() < deadline:
            run = client.get(f"/api/v1/runs/{run_id}").json()
            events = client.get(f"/api/v1/runs/{run_id}/events").json()
            if (
                run["status"] == "paused"
                and any((event.get("payload_json") or {}).get("status") == "paused" for event in events)
                and any((event.get("payload_json") or {}).get("text") == "pause before restart" for event in events)
            ):
                break
            time.sleep(0.2)
        else:
            raise TimeoutError(f"Run {run_id} did not pause")
        _write_state(state_path, {"paused_run_id": run_id, "paused_session_id": session["id"]})
        print(json.dumps({"paused_run_id": run_id}, ensure_ascii=False))


def phase_resume_paused(state_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.main import app

    state = _read_state(state_path)
    run_id = state["paused_run_id"]

    with TestClient(app) as client:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        assert run["status"] == "paused", run
        events = client.get(f"/api/v1/runs/{run_id}/events").json()
        assert any((e.get("payload_json") or {}).get("text") == "pause before restart" for e in events), events
        resume = client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"message": "continue after restart", "source": "itest"},
        )
        assert resume.status_code == 200, resume.text
        final = _wait_run(client, run_id)
        assert final["status"] == "finished", final
        report = client.get(f"/api/v1/runs/{run_id}/report").json()
        assert "pause before restart" in report["summary_markdown"], report["summary_markdown"]
        assert "continue after restart" in report["summary_markdown"], report["summary_markdown"]
        print(json.dumps({"paused_resume_finished": run_id}, ensure_ascii=False))


def phase_crash_running(state_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    client.__enter__()
    try:
        bootstrap = client.post("/api/v1/demo/bootstrap").json()
        session = _create_unique_session(client, bootstrap["agent_ids"], "running recovery smoke")
        run_id = client.post(
            f"/api/v1/chat-sessions/{session['id']}/start",
            json={"notify_feishu": False},
        ).json()["id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            events = client.get(f"/api/v1/runs/{run_id}/events").json()
            if any((event.get("payload_json") or {}).get("status") == "round_started" for event in events):
                break
            time.sleep(0.1)
        _write_state(state_path, {"running_run_id": run_id, "running_session_id": session["id"]})
        os._exit(0)
    finally:
        client.__exit__(None, None, None)


def phase_verify_running(state_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.main import app

    state = _read_state(state_path)
    run_id = state["running_run_id"]

    with TestClient(app) as client:
        final = _wait_run(client, run_id, timeout=30.0)
        assert final["status"] == "finished", final
        report = client.get(f"/api/v1/runs/{run_id}/report").json()
        events = client.get(f"/api/v1/runs/{run_id}/events").json()
        assert report["title"], report
        assert any(event["event_type"] == "message_completed" for event in events), events
        assert any((event.get("payload_json") or {}).get("status") == "finished" for event in events), events
        print(json.dumps({"running_recovered": run_id}, ensure_ascii=False))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--phase":
        phase = sys.argv[2]
        state_path = Path(sys.argv[4]).resolve()
        if phase == "setup-paused":
            phase_setup_paused(state_path)
            return
        if phase == "resume-paused":
            phase_resume_paused(state_path)
            return
        if phase == "crash-running":
            phase_crash_running(state_path)
            return
        if phase == "verify-running":
            phase_verify_running(state_path)
            return
        raise ValueError(f"Unknown phase: {phase}")

    with tempfile.TemporaryDirectory(prefix="alignhub-langgraph-recovery-") as temp_dir:
        temp_root = Path(temp_dir)
        env = _base_env(temp_root)

        paused_state = temp_root / "paused_state.json"
        running_state = temp_root / "running_state.json"

        paused_setup = _run_subprocess("--phase", "setup-paused", "--state", str(paused_state), env=env)
        paused_resume = _run_subprocess("--phase", "resume-paused", "--state", str(paused_state), env=env)
        running_crash = _run_subprocess("--phase", "crash-running", "--state", str(running_state), env=env)
        running_verify = _run_subprocess("--phase", "verify-running", "--state", str(running_state), env=env)

        print(paused_setup.stdout.strip())
        print(paused_resume.stdout.strip())
        print(running_crash.stdout.strip())
        print(running_verify.stdout.strip())
        print("langgraph recovery test passed")


if __name__ == "__main__":
    main()
