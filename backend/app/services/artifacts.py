from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.entities import MCPServerConfig, SkillDefinition
from app.schemas import SkillRead

ARTIFACT_ROOT = Path(settings.artifact_root).resolve()
SKILL_UPLOAD_ROOT = ARTIFACT_ROOT / "skills"
MCP_UPLOAD_ROOT = ARTIFACT_ROOT / "mcps"


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_slug(name: str, fallback: str = "artifact") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-._")
    return slug or fallback


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_artifact_dir(root: Path, base_name: str) -> Path:
    slug = _safe_slug(base_name)
    candidate = root / slug
    if not candidate.exists():
        return _ensure_dir(candidate)
    return _ensure_dir(root / f"{slug}-{uuid4().hex[:8]}")


def safe_extract_zip(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            member_path = (target_dir / member.filename).resolve()
            if target_dir.resolve() not in member_path.parents and member_path != target_dir.resolve():
                raise ValueError(f"Unsafe zip entry: {member.filename}")
        zf.extractall(target_dir)


def _list_relative_files(root: Path | None, *, max_items: int = 200) -> list[str]:
    if not root or not root.exists() or not root.is_dir():
        return []
    files = sorted(path for path in root.rglob("*") if path.is_file())
    rel_paths = [str(path.relative_to(root).as_posix()) for path in files[:max_items]]
    if len(files) > max_items:
        rel_paths.append(f"... 还有 {len(files) - max_items} 个文件")
    return rel_paths


def skill_to_read(row: SkillDefinition) -> SkillRead:
    package_root = Path(row.package_path) if row.package_path else None
    return SkillRead(
        id=row.id,
        name=row.name,
        description=row.description,
        content=row.content,
        source_type=row.source_type,
        package_path=row.package_path,
        entry_file=row.entry_file,
        package_files=_list_relative_files(package_root),
        enabled=row.enabled,
        builtin=row.builtin,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def cleanup_skill_artifact(row: SkillDefinition) -> None:
    if not row.package_path:
        return
    package_root = Path(row.package_path)
    if not package_root.exists():
        return
    skill_root = package_root.parent if package_root.name == "package" else package_root
    if _path_within_root(skill_root, SKILL_UPLOAD_ROOT):
        shutil.rmtree(skill_root, ignore_errors=True)


def cleanup_mcp_artifact(row: MCPServerConfig) -> None:
    if not row.jar_path:
        return
    jar_path = Path(row.jar_path)
    if jar_path.exists() and _path_within_root(jar_path, MCP_UPLOAD_ROOT):
        shutil.rmtree(jar_path.parent, ignore_errors=True)


def find_best_skill_entry(extract_dir: Path) -> Path | None:
    candidates = []
    preferred_names = {"SKILL.md", "README.md", "readme.md"}
    for path in extract_dir.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if path.name in preferred_names:
            candidates.append((0, len(path.parts), path))
        elif suffix in {".md", ".txt"}:
            candidates.append((1, len(path.parts), path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2]).lower()))
    return candidates[0][2]


def derive_skill_name(entry: Path | None, fallback: str) -> str:
    if not entry:
        return fallback
    if entry.name.upper() == "SKILL.MD":
        return entry.parent.name or fallback
    return entry.stem or fallback


def derive_skill_description(content: str) -> str:
    for line in content.splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            return text[:240]
    return "Imported skill package"


async def ensure_unique_name(db: AsyncSession, model_cls, base_name: str) -> str:
    candidate = base_name
    index = 2
    while True:
        existing = await db.execute(select(model_cls.id).where(model_cls.name == candidate))
        if not existing.first():
            return candidate
        candidate = f"{base_name} {index}"
        index += 1
