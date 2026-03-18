from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core import settings


def build_mcp_env(env_json: dict | None) -> dict[str, str]:
    merged = dict(os.environ)
    for key, value in (env_json or {}).items():
        merged[str(key)] = str(value)
    return merged


async def invoke_mcp_http(endpoint: str, payload: dict, *, headers: dict[str, str] | None = None) -> str:
    def _request() -> str:
        req = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")

    try:
        return await asyncio.to_thread(_request)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return f"HTTPError {exc.code}: {body}"
    except URLError as exc:
        return f"URLError: {exc.reason}"


async def invoke_mcp_sse(endpoint: str, payload: dict) -> str:
    def _request() -> str:
        req = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        with urlopen(req, timeout=30) as response:
            lines: list[str] = []
            for _ in range(20):
                line = response.readline().decode("utf-8", errors="replace")
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    if lines:
                        break
                    continue
                if stripped.startswith("data:"):
                    lines.append(stripped[5:].strip())
                else:
                    lines.append(stripped)
            return "\n".join(lines).strip() or "<empty sse response>"

    try:
        return await asyncio.to_thread(_request)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return f"HTTPError {exc.code}: {body}"
    except URLError as exc:
        return f"URLError: {exc.reason}"


async def invoke_mcp_stdio(
    command: str,
    args: list[Any],
    payload: dict,
    *,
    env_json: dict | None = None,
    cwd: str | None = None,
) -> str:
    process = await asyncio.create_subprocess_exec(
        command,
        *[str(arg) for arg in args],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or settings.workspace_root,
        env=build_mcp_env(env_json),
    )
    stdout, stderr = await asyncio.wait_for(
        process.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        timeout=30,
    )
    out_text = stdout.decode("utf-8", errors="replace").strip()
    err_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode == 0:
        return out_text or "<empty stdout>"
    return f"ERROR({process.returncode})\n{err_text or out_text or '<no output>'}"


def resolve_mcp_command(command: str | None) -> str | None:
    if not command:
        return None
    path = Path(command)
    if path.exists():
        return str(path)
    return shutil.which(command)


async def run_process_preview(
    command: str,
    args: list[str] | None = None,
    *,
    timeout_seconds: float = 2.5,
    env_json: dict | None = None,
) -> dict:
    args = list(args or [])
    process = await asyncio.create_subprocess_exec(
        command,
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=build_mcp_env(env_json),
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        timed_out = True
        if process.returncode is None:
            process.terminate()
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=1.5)
        except asyncio.TimeoutError:
            if process.returncode is None:
                process.kill()
            stdout, stderr = await process.communicate()
    preview = "\n".join(
        part for part in [stdout.decode("utf-8", errors="replace").strip(), stderr.decode("utf-8", errors="replace").strip()] if part
    ).strip()
    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "preview": preview[:2000],
    }


async def probe_java_runtime(resolved_command: str, *, enabled: bool = True) -> dict:
    if not enabled:
        return {}
    command_name = Path(resolved_command).name.lower()
    if "java" not in command_name:
        return {}
    result = await run_process_preview(resolved_command, ["-version"], timeout_seconds=4)
    return {
        "java_available": result["exit_code"] == 0 or bool(result["preview"]),
        "java_version": result["preview"] or "java -version returned no output",
    }


async def _http_text_request(url: str, *, method: str = "GET", payload: dict | None = None) -> str:
    def _request() -> str:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"} if payload is not None else {},
            method=method,
        )
        with urlopen(req, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")

    return await asyncio.to_thread(_request)


async def _sse_probe_request(url: str) -> str:
    def _request() -> str:
        req = Request(url, headers={"Accept": "text/event-stream"}, method="GET")
        with urlopen(req, timeout=20) as response:
            lines: list[str] = []
            for _ in range(10):
                line = response.readline().decode("utf-8", errors="replace")
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    if lines:
                        break
                    continue
                lines.append(stripped)
            return "\n".join(lines).strip() or "<sse stream connected>"

    return await asyncio.to_thread(_request)


async def test_mcp_connection(mcp) -> dict:
    started_at = datetime.now(timezone.utc)
    try:
        if mcp.transport_type == "stdio":
            resolved = resolve_mcp_command(mcp.command)
            if not resolved:
                raise ValueError("MCP command not found")
            jar_exists = bool(mcp.jar_path and Path(mcp.jar_path).exists())
            if mcp.jar_path and not jar_exists:
                raise ValueError(f"MCP jar not found: {mcp.jar_path}")
            java_info = await probe_java_runtime(resolved, enabled=bool(mcp.jar_path))
            preview = f"Resolved command: {resolved}"
        elif mcp.transport_type == "http":
            if not mcp.base_url:
                raise ValueError("MCP base_url is required")
            preview = (await _http_text_request(mcp.base_url, method="GET"))[:400]
            jar_exists = None
            java_info = {}
            resolved = None
        elif mcp.transport_type == "sse":
            if not mcp.base_url:
                raise ValueError("MCP base_url is required")
            preview = (await _sse_probe_request(mcp.base_url))[:400]
            jar_exists = None
            java_info = {}
            resolved = None
        else:
            raise ValueError(f"Unsupported transport type: {mcp.transport_type}")

        latency_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        result = {
            "success": True,
            "name": mcp.name,
            "transport_type": mcp.transport_type,
            "latency_ms": latency_ms,
            "preview": preview or "OK",
            "resolved_command": resolved if mcp.transport_type == "stdio" else None,
        }
        if mcp.transport_type == "stdio" and mcp.jar_path:
            result["jar_exists"] = jar_exists
            result.update(java_info)
        return result
    except Exception as exc:
        latency_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        return {
            "success": False,
            "name": mcp.name,
            "transport_type": mcp.transport_type,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


async def test_mcp_invoke(mcp, *, action: str = "ping", payload_json: dict | None = None) -> dict:
    payload_json = payload_json or {}
    started_at = datetime.now(timezone.utc)
    try:
        request_payload = {
            "action": action,
            "payload": payload_json,
            "agent": {"id": "test-agent", "name": "MCP Test Client"},
            "run": {"run_id": "test-run", "round_no": 0},
            "mcp": {"name": mcp.name, "transport_type": mcp.transport_type},
        }
        if mcp.transport_type == "stdio":
            resolved = resolve_mcp_command(mcp.command)
            if not resolved:
                raise ValueError("MCP command not found")
            if mcp.jar_path and not Path(mcp.jar_path).exists():
                raise ValueError(f"MCP jar not found: {mcp.jar_path}")
            preview = await invoke_mcp_stdio(resolved, list(mcp.args_json or []), request_payload, env_json=mcp.env_json)
        elif mcp.transport_type == "http":
            if not mcp.base_url:
                raise ValueError("MCP base_url is required")
            preview = await invoke_mcp_http(f"{mcp.base_url.rstrip('/')}/invoke", request_payload)
        elif mcp.transport_type == "sse":
            if not mcp.base_url:
                raise ValueError("MCP base_url is required")
            preview = await invoke_mcp_sse(f"{mcp.base_url.rstrip('/')}/invoke", request_payload)
        else:
            raise ValueError(f"Unsupported transport type: {mcp.transport_type}")

        latency_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        return {
            "success": True,
            "name": mcp.name,
            "transport_type": mcp.transport_type,
            "action": action,
            "latency_ms": latency_ms,
            "preview": preview[:1000],
        }
    except Exception as exc:
        latency_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        return {
            "success": False,
            "name": mcp.name,
            "transport_type": mcp.transport_type,
            "action": action,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


async def preview_mcp_startup(mcp) -> dict:
    started_at = datetime.now(timezone.utc)
    try:
        if mcp.transport_type != "stdio":
            raise ValueError("Startup preview only supports stdio MCPs")
        resolved = resolve_mcp_command(mcp.command)
        if not resolved:
            raise ValueError("MCP command not found")
        jar_exists = bool(mcp.jar_path and Path(mcp.jar_path).exists())
        if mcp.jar_path and not jar_exists:
            raise ValueError(f"MCP jar not found: {mcp.jar_path}")

        java_info = await probe_java_runtime(resolved, enabled=bool(mcp.jar_path))
        startup = await run_process_preview(
            resolved,
            [str(item) for item in list(mcp.args_json or [])],
            timeout_seconds=3,
            env_json=mcp.env_json,
        )
        latency_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        result = {
            "success": True,
            "name": mcp.name,
            "transport_type": mcp.transport_type,
            "latency_ms": latency_ms,
            "resolved_command": resolved,
            "jar_path": mcp.jar_path,
            "jar_exists": jar_exists if mcp.jar_path else None,
            "startup_preview": startup["preview"] or "进程已启动，但在预览时间内没有输出日志。",
            "startup_exit_code": startup["exit_code"],
            "startup_timed_out": startup["timed_out"],
        }
        result.update(java_info)
        return result
    except Exception as exc:
        latency_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        return {
            "success": False,
            "name": mcp.name,
            "transport_type": mcp.transport_type,
            "latency_ms": latency_ms,
            "error": str(exc),
        }
