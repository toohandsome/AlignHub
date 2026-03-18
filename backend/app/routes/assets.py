import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.entities import MCPServerConfig, SkillDefinition, ToolDefinition
from app.services.mcp_runtime import preview_mcp_startup as preview_runtime_mcp_startup
from app.services.mcp_runtime import test_mcp_connection, test_mcp_invoke
from app.schemas import MCPInvokeTestRequest, MCPServerCreate, MCPServerRead, MCPServerUpdate, SkillCreate, SkillRead, SkillUpdate, ToolRead
from app.services import (
    MCP_UPLOAD_ROOT,
    SKILL_UPLOAD_ROOT,
    cleanup_mcp_artifact,
    cleanup_skill_artifact,
    commit_or_409,
    delete_and_commit_or_409,
    derive_skill_description,
    derive_skill_name,
    ensure_unique_name,
    find_best_skill_entry,
    mcp_to_read,
    skill_to_read,
    tool_to_read,
    unique_artifact_dir,
)
from app.services.artifacts import safe_extract_zip

router = APIRouter()


@router.get("/tools", response_model=list[ToolRead])
async def list_tools(db: AsyncSession = Depends(get_db)):
    """列出当前系统中的内置工具定义。"""
    res = await db.execute(select(ToolDefinition).order_by(ToolDefinition.name.asc()))
    return [tool_to_read(item) for item in res.scalars().all()]


@router.get("/skills", response_model=list[SkillRead])
async def list_skills(db: AsyncSession = Depends(get_db)):
    """列出 Skill 列表。"""
    res = await db.execute(select(SkillDefinition).order_by(SkillDefinition.created_at.desc()))
    return [skill_to_read(item) for item in res.scalars().all()]


@router.get("/skills/{skill_id}", response_model=SkillRead)
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    """查看单个 Skill 详情。"""
    row = await db.get(SkillDefinition, skill_id)
    if not row:
        raise HTTPException(404, "Skill not found")
    return skill_to_read(row)


@router.post("/skills", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def create_skill(payload: SkillCreate, db: AsyncSession = Depends(get_db)):
    """创建手工录入的 Skill。"""
    row = SkillDefinition(**payload.model_dump())
    db.add(row)
    await commit_or_409(db, entity_name="skill")
    await db.refresh(row)
    return skill_to_read(row)


@router.post("/skills/upload-zip", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def upload_skill_zip(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    enabled: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
):
    """上传 zip 并自动解析为 Skill。"""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Only .zip files are supported")

    skill_dir = unique_artifact_dir(SKILL_UPLOAD_ROOT, Path(file.filename).stem)
    archive_path = skill_dir / file.filename
    archive_path.write_bytes(await file.read())

    extract_dir = skill_dir / "package"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        safe_extract_zip(archive_path, extract_dir)
    except Exception as exc:
        shutil.rmtree(skill_dir, ignore_errors=True)
        raise HTTPException(400, f"Failed to extract zip: {exc}") from exc

    entry = find_best_skill_entry(extract_dir)
    if not entry:
        shutil.rmtree(skill_dir, ignore_errors=True)
        raise HTTPException(400, "No readable SKILL.md/README.md/.md/.txt file found in zip")

    parsed_content = entry.read_text(encoding="utf-8", errors="replace")
    skill_name = await ensure_unique_name(db, SkillDefinition, name or derive_skill_name(entry, Path(file.filename).stem))
    skill_description = description or derive_skill_description(parsed_content)

    row = SkillDefinition(
        name=skill_name,
        description=skill_description,
        content=parsed_content,
        source_type="zip",
        package_path=str(extract_dir),
        entry_file=str(entry.relative_to(extract_dir).as_posix()),
        enabled=enabled,
        builtin=False,
    )
    db.add(row)
    await commit_or_409(db, entity_name="skill")
    await db.refresh(row)
    return skill_to_read(row)


@router.put("/skills/{skill_id}", response_model=SkillRead)
async def update_skill(skill_id: str, payload: SkillUpdate, db: AsyncSession = Depends(get_db)):
    """更新 Skill 元数据或内容。"""
    row = await db.get(SkillDefinition, skill_id)
    if not row:
        raise HTTPException(404, "Skill not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await commit_or_409(db, entity_name="skill")
    await db.refresh(row)
    return skill_to_read(row)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    """删除 Skill，并在需要时清理对应产物目录。"""
    row = await db.get(SkillDefinition, skill_id)
    if not row:
        raise HTTPException(404, "Skill not found")
    await delete_and_commit_or_409(db, row, entity_name="skill")
    cleanup_skill_artifact(row)


@router.get("/mcps", response_model=list[MCPServerRead])
async def list_mcps(db: AsyncSession = Depends(get_db)):
    """列出 MCP 配置。"""
    res = await db.execute(select(MCPServerConfig).order_by(MCPServerConfig.created_at.desc()))
    return [mcp_to_read(item) for item in res.scalars().all()]


@router.get("/mcps/{mcp_id}", response_model=MCPServerRead)
async def get_mcp(mcp_id: str, db: AsyncSession = Depends(get_db)):
    """查看单个 MCP 详情。"""
    row = await db.get(MCPServerConfig, mcp_id)
    if not row:
        raise HTTPException(404, "MCP not found")
    return mcp_to_read(row)


@router.post("/mcps", response_model=MCPServerRead, status_code=status.HTTP_201_CREATED)
async def create_mcp(payload: MCPServerCreate, db: AsyncSession = Depends(get_db)):
    """创建 MCP 配置。"""
    row = MCPServerConfig(**payload.model_dump())
    db.add(row)
    await commit_or_409(db, entity_name="mcp")
    await db.refresh(row)
    return mcp_to_read(row)


@router.post("/mcps/upload-jar", response_model=MCPServerRead, status_code=status.HTTP_201_CREATED)
async def upload_mcp_jar(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    description: str = Form(default=""),
    enabled: bool = Form(default=True),
    args_json: str = Form(default="[]"),
    db: AsyncSession = Depends(get_db),
):
    """上传 jar，并自动生成 stdio 型 MCP 配置。"""
    if not file.filename or not file.filename.lower().endswith(".jar"):
        raise HTTPException(400, "Only .jar files are supported")

    try:
        parsed_args = json.loads(args_json or "[]")
        if not isinstance(parsed_args, list):
            raise ValueError("args_json must be a JSON array")
        extra_args = [str(item) for item in parsed_args]
    except Exception as exc:
        raise HTTPException(400, f"Invalid args_json: {exc}") from exc

    mcp_dir = unique_artifact_dir(MCP_UPLOAD_ROOT, Path(file.filename).stem)
    jar_path = mcp_dir / file.filename
    jar_path.write_bytes(await file.read())

    row = MCPServerConfig(
        name=await ensure_unique_name(db, MCPServerConfig, name or Path(file.filename).stem),
        transport_type="stdio",
        description=description or f"Imported from jar package {file.filename}",
        command="java",
        args_json=["-jar", str(jar_path), *extra_args],
        env_json={},
        base_url=None,
        jar_path=str(jar_path),
        enabled=enabled,
    )
    db.add(row)
    await commit_or_409(db, entity_name="mcp")
    await db.refresh(row)
    return mcp_to_read(row)


@router.put("/mcps/{mcp_id}", response_model=MCPServerRead)
async def update_mcp(mcp_id: str, payload: MCPServerUpdate, db: AsyncSession = Depends(get_db)):
    """更新 MCP 配置。"""
    row = await db.get(MCPServerConfig, mcp_id)
    if not row:
        raise HTTPException(404, "MCP not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await commit_or_409(db, entity_name="mcp")
    await db.refresh(row)
    return mcp_to_read(row)


@router.delete("/mcps/{mcp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp(mcp_id: str, db: AsyncSession = Depends(get_db)):
    """删除 MCP，并在需要时清理 jar 产物。"""
    row = await db.get(MCPServerConfig, mcp_id)
    if not row:
        raise HTTPException(404, "MCP not found")
    await delete_and_commit_or_409(db, row, entity_name="mcp")
    cleanup_mcp_artifact(row)


@router.post("/mcps/{mcp_id}/test")
async def probe_mcp(mcp_id: str, db: AsyncSession = Depends(get_db)):
    """执行 MCP 连通性测试。"""
    row = await db.get(MCPServerConfig, mcp_id)
    if not row:
        raise HTTPException(404, "MCP not found")
    return await test_mcp_connection(row)


@router.post("/mcps/{mcp_id}/invoke-test")
async def invoke_test_mcp(mcp_id: str, payload: MCPInvokeTestRequest, db: AsyncSession = Depends(get_db)):
    """执行一次 MCP 调用测试。"""
    row = await db.get(MCPServerConfig, mcp_id)
    if not row:
        raise HTTPException(404, "MCP not found")
    return await test_mcp_invoke(row, action=payload.action, payload_json=payload.payload_json)


@router.post("/mcps/{mcp_id}/startup-preview")
async def preview_mcp_startup(mcp_id: str, db: AsyncSession = Depends(get_db)):
    """预览 stdio MCP 的启动日志。"""
    row = await db.get(MCPServerConfig, mcp_id)
    if not row:
        raise HTTPException(404, "MCP not found")
    return await preview_runtime_mcp_startup(row)
