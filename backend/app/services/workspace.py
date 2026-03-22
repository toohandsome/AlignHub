from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.core import settings

WORKSPACE_IGNORED_NAMES = {
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    "artifacts",
    "node_modules",
}
WORKSPACE_IGNORED_SUFFIXES = {".db", ".log", ".pyc", ".pyo", ".sqlite", ".tsbuildinfo"}
WORKSPACE_TOP_LEVEL_INCLUDE = {
    "README.md",
    "FEISHU_SETUP.md",
    "backend",
    "frontend",
}


def _dynamic_ignored_names() -> set[str]:
    ignored = set(WORKSPACE_IGNORED_NAMES)
    try:
        source_root = workspace_source_root()
        artifact_root = Path(settings.artifact_root).resolve()
        if artifact_root == source_root or source_root in artifact_root.parents:
            ignored.add(artifact_root.name)
    except Exception:
        pass
    return ignored


def workspace_source_root() -> Path:
    return Path(settings.workspace_root).resolve()


def workspace_target_root(run_id: str) -> Path:
    return (Path(settings.artifact_root) / "workspaces" / run_id).resolve()


def _workspace_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    ignored_names = _dynamic_ignored_names()
    for name in names:
        suffix = Path(name).suffix.lower()
        if name in ignored_names or suffix in WORKSPACE_IGNORED_SUFFIXES:
            ignored.add(name)
    return ignored


def prepare_run_workspace(run_id: str) -> str:
    source_root = workspace_source_root()
    target_root = workspace_target_root(run_id)
    if target_root.exists():
        return str(target_root)

    target_root.mkdir(parents=True, exist_ok=True)
    for entry_name in WORKSPACE_TOP_LEVEL_INCLUDE:
        source = source_root / entry_name
        if not source.exists():
            continue
        target = target_root / entry_name
        if source.is_dir():
            shutil.copytree(source, target, ignore=_workspace_ignore)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return str(target_root)


def cleanup_run_workspace(run_id: str) -> None:
    shutil.rmtree(workspace_target_root(run_id), ignore_errors=True)


async def prepare_run_workspace_async(run_id: str) -> str:
    return await asyncio.to_thread(prepare_run_workspace, run_id)


async def cleanup_run_workspace_async(run_id: str) -> None:
    await asyncio.to_thread(cleanup_run_workspace, run_id)
