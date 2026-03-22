from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool

from app.entities import AgentConfig
from app.services.mcp_runtime import invoke_mcp_http, invoke_mcp_sse, invoke_mcp_stdio


ToolStarted = Callable[[str, str, dict[str, Any]], Awaitable[None]]
ToolFinished = Callable[[str, str, dict[str, Any], str], Awaitable[None]]
ToolFailed = Callable[[str, str, dict[str, Any], Exception], Awaitable[None]]


@dataclass
class LangGraphToolRuntimeContext:
    workspace_root: str
    run_id: str
    agent_id: str
    agent_name: str
    round_no_getter: Callable[[], int] | None = None

    @property
    def round_no(self) -> int:
        if self.round_no_getter is None:
            return 0
        try:
            return int(self.round_no_getter())
        except Exception:
            return 0


class WorkspaceBoundary:
    def __init__(self, workspace_root: str) -> None:
        self.root = Path(workspace_root).resolve()

    def resolve(self, relative_path: str) -> Path:
        target = (self.root / relative_path).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"Path escapes workspace: {relative_path}")
        return target

    def ensure_parent(self, relative_path: str) -> Path:
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class LangGraphToolFactory:
    def build_tools(
        self,
        agent: AgentConfig,
        *,
        run_id: str,
        workspace_root: str,
        round_no_getter: Callable[[], int] | None,
        on_tool_started: ToolStarted,
        on_tool_finished: ToolFinished,
        on_tool_failed: ToolFailed,
    ) -> list[StructuredTool]:
        ctx = LangGraphToolRuntimeContext(
            workspace_root=workspace_root,
            run_id=run_id,
            agent_id=agent.id,
            agent_name=agent.name,
            round_no_getter=round_no_getter,
        )
        tools: list[StructuredTool] = []
        mounted = set(binding.tool.name for binding in agent.tool_bindings)

        if "topic_probe" in mounted:
            tools.append(self._topic_probe(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "list_files" in mounted:
            tools.append(self._list_files(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "read_file" in mounted:
            tools.append(self._read_file(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "write_file" in mounted:
            tools.append(self._write_file(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "edit_file" in mounted:
            tools.append(self._edit_file(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "git_status" in mounted:
            tools.append(self._git_status(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "git_log" in mounted:
            tools.append(self._git_log(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "git_diff" in mounted:
            tools.append(self._git_diff(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "git_add" in mounted:
            tools.append(self._git_add(ctx, on_tool_started, on_tool_finished, on_tool_failed))
        if "git_commit" in mounted:
            tools.append(self._git_commit(ctx, on_tool_started, on_tool_finished, on_tool_failed))

        tools.extend(self._mcp_tools(agent, ctx, on_tool_started, on_tool_finished, on_tool_failed))
        return tools

    async def _run_tool(
        self,
        name: str,
        tool_input: dict[str, Any],
        runner: Callable[[], Awaitable[str]],
        on_tool_started: ToolStarted,
        on_tool_finished: ToolFinished,
        on_tool_failed: ToolFailed,
    ) -> str:
        call_id = uuid.uuid4().hex
        await on_tool_started(call_id, name, tool_input)
        try:
            output = await runner()
        except Exception as exc:
            await on_tool_failed(call_id, name, tool_input, exc)
            raise
        await on_tool_finished(call_id, name, tool_input, output)
        return output

    def _topic_probe(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        async def topic_probe(topic: str) -> str:
            async def runner() -> str:
                return f"[debug:{ctx.agent_name}] topic length={len(topic)}; hint=聚焦可执行结论。"

            return await self._run_tool("topic_probe", {"topic": topic}, runner, on_tool_started, on_tool_finished, on_tool_failed)

        return StructuredTool.from_function(coroutine=topic_probe, name="topic_probe", description="Inspect the current topic and return a short verification note.")

    def _list_files(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        boundary = WorkspaceBoundary(ctx.workspace_root)

        async def list_files(path: str = ".", recursive: bool = False, limit: int = 50) -> str:
            async def runner() -> str:
                def _list_sync() -> str:
                    target = boundary.resolve(path)
                    if not target.exists():
                        return f"Path not found: {path}"
                    if not target.is_dir():
                        return f"Path is not a directory: {path}"
                    items = target.rglob("*") if recursive else target.iterdir()
                    rows: list[str] = []
                    for item in items:
                        rel = item.relative_to(boundary.root).as_posix()
                        kind = "dir" if item.is_dir() else "file"
                        rows.append(f"{kind}: {rel}")
                        if len(rows) >= max(1, min(limit, 200)):
                            break
                    return "\n".join(rows or ["<empty directory>"])

                return await asyncio.to_thread(_list_sync)

            return await self._run_tool(
                "list_files",
                {"path": path, "recursive": recursive, "limit": limit},
                runner,
                on_tool_started,
                on_tool_finished,
                on_tool_failed,
            )

        return StructuredTool.from_function(coroutine=list_files, name="list_files", description="List files under the workspace or a subdirectory.")

    def _read_file(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        boundary = WorkspaceBoundary(ctx.workspace_root)

        async def read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
            async def runner() -> str:
                def _read_sync() -> str:
                    target = boundary.resolve(path)
                    if not target.exists():
                        return f"File not found: {path}"
                    if not target.is_file():
                        return f"Path is not a file: {path}"
                    text = target.read_text(encoding="utf-8", errors="replace")
                    lines = text.splitlines()
                    start = max(start_line - 1, 0)
                    end = max(end_line, start_line)
                    selected = lines[start:end]
                    numbered = [f"{idx + start + 1}: {line}" for idx, line in enumerate(selected)]
                    return "\n".join(numbered) if numbered else "<empty file>"

                return await asyncio.to_thread(_read_sync)

            return await self._run_tool(
                "read_file",
                {"path": path, "start_line": start_line, "end_line": end_line},
                runner,
                on_tool_started,
                on_tool_finished,
                on_tool_failed,
            )

        return StructuredTool.from_function(coroutine=read_file, name="read_file", description="Read a text file from the workspace.")

    def _write_file(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        boundary = WorkspaceBoundary(ctx.workspace_root)

        async def write_file(path: str, content: str, overwrite: bool = True) -> str:
            async def runner() -> str:
                def _write_sync() -> str:
                    target = boundary.ensure_parent(path)
                    if target.exists() and target.is_dir():
                        return f"Path is a directory, not a file: {path}"
                    if target.exists() and not overwrite:
                        return f"File already exists and overwrite is false: {path}"
                    target.write_text(content, encoding="utf-8")
                    return f"Wrote {len(content)} characters to {target.relative_to(boundary.root).as_posix()}"

                return await asyncio.to_thread(_write_sync)

            return await self._run_tool(
                "write_file",
                {"path": path, "content": content, "overwrite": overwrite},
                runner,
                on_tool_started,
                on_tool_finished,
                on_tool_failed,
            )

        return StructuredTool.from_function(coroutine=write_file, name="write_file", description="Write a text file into the workspace.")

    def _edit_file(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        boundary = WorkspaceBoundary(ctx.workspace_root)

        async def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
            async def runner() -> str:
                def _edit_sync() -> str:
                    target = boundary.resolve(path)
                    if not target.exists():
                        return f"File not found: {path}"
                    if not target.is_file():
                        return f"Path is not a file: {path}"
                    text = target.read_text(encoding="utf-8", errors="replace")
                    if old_text not in text:
                        return f"Target text not found in {path}"
                    count = text.count(old_text) if replace_all else 1
                    updated = text.replace(old_text, new_text, -1 if replace_all else 1)
                    target.write_text(updated, encoding="utf-8")
                    return f"Updated {count} occurrence(s) in {path}"

                return await asyncio.to_thread(_edit_sync)

            return await self._run_tool(
                "edit_file",
                {"path": path, "old_text": old_text, "new_text": new_text, "replace_all": replace_all},
                runner,
                on_tool_started,
                on_tool_finished,
                on_tool_failed,
            )

        return StructuredTool.from_function(coroutine=edit_file, name="edit_file", description="Replace text in a workspace file.")

    @staticmethod
    async def _run_git(root: str, args: list[str]) -> str:
        def _git_sync() -> str:
            process = subprocess.run(
                ["git", *args],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            output = (process.stdout or "").strip()
            error = (process.stderr or "").strip()
            body = output or error or "<no output>"
            prefix = "OK" if process.returncode == 0 else f"ERROR({process.returncode})"
            return f"{prefix}\n{body}"

        return await asyncio.to_thread(_git_sync)

    def _git_status(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        async def git_status() -> str:
            async def runner() -> str:
                return await self._run_git(ctx.workspace_root, ["status", "--short", "--branch"])

            return await self._run_tool("git_status", {}, runner, on_tool_started, on_tool_finished, on_tool_failed)

        return StructuredTool.from_function(coroutine=git_status, name="git_status", description="Run git status in the workspace.")

    def _git_log(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        async def git_log(limit: int = 10) -> str:
            async def runner() -> str:
                bounded = max(1, min(limit, 30))
                return await self._run_git(ctx.workspace_root, ["log", f"-n{bounded}", "--oneline", "--decorate"])

            return await self._run_tool("git_log", {"limit": limit}, runner, on_tool_started, on_tool_finished, on_tool_failed)

        return StructuredTool.from_function(coroutine=git_log, name="git_log", description="Show recent git commits.")

    def _git_diff(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        async def git_diff(pathspec: str = "") -> str:
            async def runner() -> str:
                args = ["diff"]
                if pathspec:
                    args.extend(["--", pathspec])
                return await self._run_git(ctx.workspace_root, args)

            return await self._run_tool("git_diff", {"pathspec": pathspec}, runner, on_tool_started, on_tool_finished, on_tool_failed)

        return StructuredTool.from_function(coroutine=git_diff, name="git_diff", description="Show git diff for the workspace or a path.")

    def _git_add(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        async def git_add(pathspec: str = ".") -> str:
            async def runner() -> str:
                return await self._run_git(ctx.workspace_root, ["add", "--", pathspec])

            return await self._run_tool("git_add", {"pathspec": pathspec}, runner, on_tool_started, on_tool_finished, on_tool_failed)

        return StructuredTool.from_function(coroutine=git_add, name="git_add", description="Stage files with git add.")

    def _git_commit(self, ctx: LangGraphToolRuntimeContext, on_tool_started: ToolStarted, on_tool_finished: ToolFinished, on_tool_failed: ToolFailed) -> StructuredTool:
        async def git_commit(message: str) -> str:
            async def runner() -> str:
                return await self._run_git(ctx.workspace_root, ["commit", "-m", message])

            return await self._run_tool("git_commit", {"message": message}, runner, on_tool_started, on_tool_finished, on_tool_failed)

        return StructuredTool.from_function(coroutine=git_commit, name="git_commit", description="Create a git commit with a message.")

    def _mcp_tools(
        self,
        agent: AgentConfig,
        ctx: LangGraphToolRuntimeContext,
        on_tool_started: ToolStarted,
        on_tool_finished: ToolFinished,
        on_tool_failed: ToolFailed,
    ) -> list[StructuredTool]:
        tools: list[StructuredTool] = []
        for binding in agent.mcp_bindings:
            mcp = binding.mcp
            if not mcp.enabled:
                continue
            slug = "_".join(part for part in "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in mcp.name).strip("_").lower().split("_") if part) or "server"
            tool_name = f"mcp_{slug}"
            endpoint = (mcp.base_url or "").rstrip("/")
            command = mcp.command
            args = list(mcp.args_json or [])
            env_json = dict(mcp.env_json or {})
            transport_type = mcp.transport_type

            async def mcp_tool(action: str, payload_json: str = "{}", *, _mcp_name=mcp.name, _endpoint=endpoint, _command=command, _args=args, _env_json=env_json, _transport=transport_type, _tool_name=tool_name) -> str:
                async def runner() -> str:
                    try:
                        payload = json.loads(payload_json or "{}")
                    except json.JSONDecodeError as exc:
                        return f"Invalid payload_json: {exc}"
                    request_payload = {
                        "action": action,
                        "payload": payload,
                        "agent": {"id": ctx.agent_id, "name": ctx.agent_name},
                        "run": {"run_id": ctx.run_id, "round_no": ctx.round_no},
                        "mcp": {"name": _mcp_name, "transport_type": _transport},
                    }
                    if _transport == "stdio":
                        if not _command:
                            return f"MCP '{_mcp_name}' has no command configured."
                        return await invoke_mcp_stdio(_command, _args, request_payload, env_json=_env_json, cwd=ctx.workspace_root)
                    if _transport == "http":
                        if not _endpoint:
                            return f"MCP '{_mcp_name}' has no base_url configured."
                        return await invoke_mcp_http(f"{_endpoint}/invoke", request_payload)
                    if _transport == "sse":
                        if not _endpoint:
                            return f"MCP '{_mcp_name}' has no base_url configured."
                        return await invoke_mcp_sse(f"{_endpoint}/invoke", request_payload)
                    return f"Unsupported MCP transport type: {_transport}"

                return await self._run_tool(
                    _tool_name,
                    {"action": action, "payload_json": payload_json},
                    runner,
                    on_tool_started,
                    on_tool_finished,
                    on_tool_failed,
                )

            tools.append(
                StructuredTool.from_function(
                    coroutine=mcp_tool,
                    name=tool_name,
                    description=(
                        f"Invoke mounted MCP server '{mcp.name}'. Description: {mcp.description or 'No description'}. "
                        "Provide action and payload_json."
                    ),
                )
            )
        return tools
