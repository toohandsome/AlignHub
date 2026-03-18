from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse, Toolkit


@dataclass
class ToolRuntimeContext:
    """工具运行时上下文。

    它为工具提供：
    - 当前工作区目录
    - 当前 Run / Agent 标识
    - 当前轮次（通过 getter 动态读取，避免轮次写死）
    """
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
    """用于约束文件系统工具访问范围，避免路径越界。"""
    def __init__(self, workspace_root: str) -> None:
        self.root = Path(workspace_root).resolve()

    def resolve(self, relative_path: str) -> Path:
        """把相对路径解析为绝对路径，并校验其仍在工作区内。"""
        target = (self.root / relative_path).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"Path escapes workspace: {relative_path}")
        return target

    def ensure_parent(self, relative_path: str) -> Path:
        """确保目标文件的父目录存在，便于写文件类工具直接落盘。"""
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class BaseToolPlugin:
    """所有内置工具插件的统一抽象。"""
    name: str
    category: str
    description: str

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        raise NotImplementedError

    @staticmethod
    def response(text: str) -> ToolResponse:
        return ToolResponse(content=[TextBlock(type="text", text=text)], is_last=True)


class TopicProbeTool(BaseToolPlugin):
    name = "topic_probe"
    category = "debug"
    description = "Inspect the current topic and return a short verification note."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        # 这个工具主要用于调试和提示模型聚焦当前议题，
        # 不直接访问外部资源，因此实现保持轻量。
        async def topic_probe(topic: str) -> ToolResponse:
            """Inspect the current discussion topic.

            Args:
                topic (str): The topic that agents are discussing.
            """
            text = f"[debug:{context.agent_name}] topic length={len(topic)}; hint=聚焦可执行结论。"
            return self.response(text)

        toolkit.register_tool_function(topic_probe)


class ListFilesTool(BaseToolPlugin):
    name = "list_files"
    category = "filesystem"
    description = "List files under the workspace or a subdirectory."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        boundary = WorkspaceBoundary(context.workspace_root)

        async def list_files(path: str = ".", recursive: bool = False, limit: int = 50) -> ToolResponse:
            # 仅允许列出工作区内的文件，避免模型扫描宿主机任意目录。
            """List files in a workspace directory.

            Args:
                path (str): Relative directory path in workspace.
                recursive (bool): Whether to recursively list children.
                limit (int): Maximum number of entries to return.
            """
            target = boundary.resolve(path)
            if not target.exists():
                return self.response(f"Path not found: {path}")
            if not target.is_dir():
                return self.response(f"Path is not a directory: {path}")

            items = target.rglob("*") if recursive else target.iterdir()
            rows: list[str] = []
            for item in items:
                rel = item.relative_to(boundary.root).as_posix()
                kind = "dir" if item.is_dir() else "file"
                rows.append(f"{kind}: {rel}")
                if len(rows) >= max(1, min(limit, 200)):
                    break
            if not rows:
                rows = ["<empty directory>"]
            return self.response("\n".join(rows))

        toolkit.register_tool_function(list_files)


class ReadFileTool(BaseToolPlugin):
    name = "read_file"
    category = "filesystem"
    description = "Read a text file from the workspace."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        boundary = WorkspaceBoundary(context.workspace_root)

        async def read_file(path: str, start_line: int = 1, end_line: int = 200) -> ToolResponse:
            # 按行号截断读取，避免把大文件一次性全部喂给模型。
            """Read a text file in the workspace.

            Args:
                path (str): Relative file path in workspace.
                start_line (int): First line number to include.
                end_line (int): Last line number to include.
            """
            target = boundary.resolve(path)
            if not target.exists():
                return self.response(f"File not found: {path}")
            if not target.is_file():
                return self.response(f"Path is not a file: {path}")

            text = target.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            start = max(start_line - 1, 0)
            end = max(end_line, start_line)
            selected = lines[start:end]
            numbered = [f"{idx + start + 1}: {line}" for idx, line in enumerate(selected)]
            return self.response("\n".join(numbered) if numbered else "<empty file>")

        toolkit.register_tool_function(read_file)


class WriteFileTool(BaseToolPlugin):
    name = "write_file"
    category = "filesystem"
    description = "Write a text file into the workspace."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        boundary = WorkspaceBoundary(context.workspace_root)

        async def write_file(path: str, content: str, overwrite: bool = True) -> ToolResponse:
            # 写文件前要同时处理三类边界：
            # 1. 路径越界
            # 2. 目标实际上是目录
            # 3. overwrite=false 时已有文件
            """Write content to a workspace file.

            Args:
                path (str): Relative file path in workspace.
                content (str): File content to write.
                overwrite (bool): Whether to overwrite an existing file.
            """
            try:
                target = boundary.ensure_parent(path)
                if target.exists() and target.is_dir():
                    return self.response(f"Path is a directory, not a file: {path}")
                if target.exists() and not overwrite:
                    return self.response(f"File already exists and overwrite is false: {path}")
                target.write_text(content, encoding="utf-8")
                return self.response(f"Wrote {len(content)} characters to {target.relative_to(boundary.root).as_posix()}")
            except OSError as exc:
                return self.response(f"Failed to write file {path}: {exc}")

        toolkit.register_tool_function(write_file)


class EditFileTool(BaseToolPlugin):
    name = "edit_file"
    category = "filesystem"
    description = "Replace text in a workspace file."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        boundary = WorkspaceBoundary(context.workspace_root)

        async def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> ToolResponse:
            # 文本替换型编辑适合给 Agent 做“小范围修补”，
            # 不适合复杂 AST 级改动，因此这里保持接口简单清晰。
            """Edit a file by replacing text.

            Args:
                path (str): Relative file path in workspace.
                old_text (str): Source text to replace.
                new_text (str): Replacement text.
                replace_all (bool): Whether to replace all matches.
            """
            try:
                target = boundary.resolve(path)
                if not target.exists():
                    return self.response(f"File not found: {path}")
                if not target.is_file():
                    return self.response(f"Path is not a file: {path}")
                text = target.read_text(encoding="utf-8", errors="replace")
                if old_text not in text:
                    return self.response(f"Target text not found in {path}")
                count = text.count(old_text) if replace_all else 1
                updated = text.replace(old_text, new_text, -1 if replace_all else 1)
                target.write_text(updated, encoding="utf-8")
                return self.response(f"Updated {count} occurrence(s) in {path}")
            except OSError as exc:
                return self.response(f"Failed to edit file {path}: {exc}")

        toolkit.register_tool_function(edit_file)


class BaseGitTool(BaseToolPlugin):
    category = "git"

    @staticmethod
    def run_git(root: str, args: list[str]) -> str:
        """统一执行 git 子命令，并返回标准化文本结果。"""
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


class GitStatusTool(BaseGitTool):
    name = "git_status"
    description = "Run git status in the workspace."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        async def git_status() -> ToolResponse:
            """Show git working tree status."""
            return self.response(self.run_git(context.workspace_root, ["status", "--short", "--branch"]))

        toolkit.register_tool_function(git_status)


class GitLogTool(BaseGitTool):
    name = "git_log"
    description = "Show recent git commits."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        async def git_log(limit: int = 10) -> ToolResponse:
            """Show recent git commits.

            Args:
                limit (int): Maximum number of commits to show.
            """
            limit = max(1, min(limit, 30))
            return self.response(
                self.run_git(
                    context.workspace_root,
                    ["log", f"-n{limit}", "--oneline", "--decorate"],
                ),
            )

        toolkit.register_tool_function(git_log)


class GitDiffTool(BaseGitTool):
    name = "git_diff"
    description = "Show git diff for the workspace or a path."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        async def git_diff(pathspec: str = "") -> ToolResponse:
            """Show git diff.

            Args:
                pathspec (str): Optional relative file or directory path.
            """
            args = ["diff"]
            if pathspec:
                args.extend(["--", pathspec])
            return self.response(self.run_git(context.workspace_root, args))

        toolkit.register_tool_function(git_diff)


class GitAddTool(BaseGitTool):
    name = "git_add"
    description = "Stage files with git add."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        async def git_add(pathspec: str = ".") -> ToolResponse:
            """Stage files with git add.

            Args:
                pathspec (str): File or directory path to stage.
            """
            return self.response(self.run_git(context.workspace_root, ["add", "--", pathspec]))

        toolkit.register_tool_function(git_add)


class GitCommitTool(BaseGitTool):
    name = "git_commit"
    description = "Create a git commit with a message."

    def register(self, toolkit: Toolkit, context: ToolRuntimeContext) -> None:
        async def git_commit(message: str) -> ToolResponse:
            """Create a git commit.

            Args:
                message (str): Commit message.
            """
            return self.response(self.run_git(context.workspace_root, ["commit", "-m", message]))

        toolkit.register_tool_function(git_commit)


TOOL_REGISTRY: dict[str, BaseToolPlugin] = {
    "topic_probe": TopicProbeTool(),
    "list_files": ListFilesTool(),
    "read_file": ReadFileTool(),
    "write_file": WriteFileTool(),
    "edit_file": EditFileTool(),
    "git_status": GitStatusTool(),
    "git_log": GitLogTool(),
    "git_diff": GitDiffTool(),
    "git_add": GitAddTool(),
    "git_commit": GitCommitTool(),
}
