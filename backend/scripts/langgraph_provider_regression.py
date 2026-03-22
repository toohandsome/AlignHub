from __future__ import annotations

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


def _providers_from_env() -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []

    if os.getenv("OPENAI_API_KEY"):
        specs.append(
            (
                "openai",
                {
                    "provider_type": "openai",
                    "name": "openai-live",
                    "api_key": os.getenv("OPENAI_API_KEY"),
                    "organization": os.getenv("OPENAI_ORG"),
                    "model_name": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    "extra_config_json": {},
                },
            )
        )

    if os.getenv("OPENROUTER_API_KEY"):
        specs.append(
            (
                "openrouter",
                {
                    "provider_type": "openrouter",
                    "name": "openrouter-live",
                    "api_key": os.getenv("OPENROUTER_API_KEY"),
                    "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                    "model_name": os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
                    "extra_config_json": {},
                },
            )
        )

    if os.getenv("ANTHROPIC_API_KEY"):
        specs.append(
            (
                "anthropic",
                {
                    "provider_type": "anthropic",
                    "name": "anthropic-live",
                    "api_key": os.getenv("ANTHROPIC_API_KEY"),
                    "model_name": os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                    "extra_config_json": {},
                },
            )
        )

    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        specs.append(
            (
                "azure",
                {
                    "provider_type": "azure",
                    "name": "azure-openai-live",
                    "api_key": os.getenv("AZURE_OPENAI_API_KEY"),
                    "base_url": os.getenv("AZURE_OPENAI_ENDPOINT"),
                    "model_name": os.getenv("AZURE_OPENAI_MODEL", "gpt-4.1-mini"),
                    "extra_config_json": {
                        "client_kwargs": {
                            "azure_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT"),
                            "api_version": os.getenv("AZURE_OPENAI_API_VERSION"),
                            "azure_deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_MODEL", "gpt-4.1-mini"),
                        }
                    },
                },
            )
        )

    if os.getenv("OLLAMA_BASE_URL"):
        specs.append(
            (
                "ollama",
                {
                    "provider_type": "ollama",
                    "name": "ollama-live",
                    "base_url": os.getenv("OLLAMA_BASE_URL"),
                    "model_name": os.getenv("OLLAMA_MODEL", "llama3.1"),
                    "extra_config_json": {},
                },
            )
        )

    return specs


def _provider_env(temp_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["APP_DATABASE_URL"] = _sqlite_url(temp_root / "provider_regression.db")
    env["APP_LANGGRAPH_CHECKPOINT_PATH"] = str((temp_root / "langgraph_checkpoints.sqlite").resolve())
    env["APP_ARTIFACT_ROOT"] = str((temp_root / "artifacts").resolve())
    env["APP_WORKSPACE_ROOT"] = str(REPO_ROOT.resolve())
    env["APP_CLEANUP_RUN_WORKSPACE_ON_FINISH"] = "false"
    return env


def _wait_run(client: Any, run_id: str, *, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = client.get(f"/api/v1/runs/{run_id}").json()
        if last["status"] in {"finished", "failed", "stopped"}:
            return last
        time.sleep(1.0)
    raise TimeoutError(f"Run {run_id} did not finish in time: {last}")


def _run_single_provider(name: str, spec: dict[str, Any]) -> None:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app.main import app

    unique = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
        provider = client.post(
            "/api/v1/providers",
            json={
                "provider_type": spec["provider_type"],
                "name": f"{spec['name']}-{unique}",
                "api_key": spec.get("api_key"),
                "base_url": spec.get("base_url"),
                "organization": spec.get("organization"),
                "extra_config_json": {},
            },
        )
        assert provider.status_code == 201, provider.text
        provider_id = provider.json()["id"]

        model = client.post(
            "/api/v1/models",
            json={
                "provider_id": provider_id,
                "model_name": spec["model_name"],
                "temperature": 0.2,
                "max_tokens": 256,
                "stream_enabled": False,
                "formatter_type": "auto",
                "extra_config_json": spec.get("extra_config_json", {}),
            },
        )
        assert model.status_code == 201, model.text
        model_id = model.json()["id"]

        model_test = client.post(f"/api/v1/models/{model_id}/test")
        assert model_test.status_code == 200, model_test.text

        participant = client.post(
            "/api/v1/agents",
            json={
                "name": f"{name}-participant-{unique}",
                "role": "Participant",
                "persona": "Participant",
                "system_prompt": "请在多智能体讨论中给出简洁、结构化、可执行的判断。",
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
                "name": f"{name}-moderator-{unique}",
                "role": "Moderator",
                "persona": "Moderator",
                "system_prompt": "你负责主持多智能体讨论并判断何时结束。",
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
                "name": f"LG provider regression {name} {unique}",
                "topic": f"请评估 {name} provider 在 LangGraph 运行时下的基本可用性。",
                "max_rounds": 2,
                "status": "draft",
                "agent_ids": [participant.json()["id"], moderator.json()["id"]],
                "feishu_enabled": False,
            },
        )
        assert session.status_code == 201, session.text
        session_id = session.json()["id"]

        start = client.post(
            f"/api/v1/chat-sessions/{session_id}/start",
            json={"notify_feishu": False},
        )
        assert start.status_code == 200, start.text
        run_id = start.json()["id"]
        final = _wait_run(client, run_id)
        assert final["status"] == "finished", final

        report = client.get(f"/api/v1/runs/{run_id}/report")
        assert report.status_code == 200, report.text
        events = client.get(f"/api/v1/runs/{run_id}/events").json()
        assert any(event["event_type"] == "message_completed" for event in events), events
        assert any(event["event_type"] == "report_generated" for event in events), events
        print(f"[ok] provider={name} run={run_id}")


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--provider":
        provider_name = sys.argv[2]
        specs = dict(_providers_from_env())
        if provider_name not in specs:
            raise ValueError(f"Provider env not configured: {provider_name}")
        _run_single_provider(provider_name, specs[provider_name])
        return

    providers = _providers_from_env()
    if not providers:
        print("No real provider credentials found; skipping LangGraph provider regression.")
        return

    print("LangGraph real provider regression targets:", [name for name, _ in providers])
    for name, _ in providers:
        with tempfile.TemporaryDirectory(prefix=f"alignhub-langgraph-{name}-") as temp_dir:
            env = _provider_env(Path(temp_dir))
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--provider", name],
                cwd=str(REPO_ROOT),
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            print(result.stdout.strip())
    print("langgraph provider regression passed")


if __name__ == "__main__":
    main()
