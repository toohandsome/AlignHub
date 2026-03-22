from __future__ import annotations

from app.db import SessionLocal
from app.entities import ToolDefinition
from sqlalchemy import select


BUILTIN_TOOL_SPECS: list[dict[str, str]] = [
    {"name": "topic_probe", "category": "debug", "description": "Inspect the current topic and return a short verification note."},
    {"name": "list_files", "category": "filesystem", "description": "List files under the workspace or a subdirectory."},
    {"name": "read_file", "category": "filesystem", "description": "Read a text file from the workspace."},
    {"name": "write_file", "category": "filesystem", "description": "Write a text file into the workspace."},
    {"name": "edit_file", "category": "filesystem", "description": "Replace text in a workspace file."},
    {"name": "git_status", "category": "git", "description": "Run git status in the workspace."},
    {"name": "git_log", "category": "git", "description": "Show recent git commits."},
    {"name": "git_diff", "category": "git", "description": "Show git diff for the workspace or a path."},
    {"name": "git_add", "category": "git", "description": "Stage files with git add."},
    {"name": "git_commit", "category": "git", "description": "Create a git commit with a message."},
]


async def sync_builtin_tools() -> None:
    async with SessionLocal() as db:
        existing = {row.name: row for row in (await db.execute(select(ToolDefinition))).scalars().all()}
        for spec in BUILTIN_TOOL_SPECS:
            if spec["name"] in existing:
                row = existing[spec["name"]]
                row.category = spec["category"]
                row.description = spec["description"]
                row.schema_json = {"name": spec["name"]}
                row.builtin = True
                row.enabled = True
            else:
                db.add(
                    ToolDefinition(
                        name=spec["name"],
                        category=spec["category"],
                        description=spec["description"],
                        schema_json={"name": spec["name"]},
                        builtin=True,
                        enabled=True,
                    )
                )
        await db.commit()
