from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _extract_integrity_message(exc: IntegrityError, entity_name: str) -> str:
    raw = str(getattr(exc, "orig", exc))
    lowered = raw.lower()
    if "unique constraint failed" in lowered:
        detail = raw.split(":", maxsplit=1)[-1].strip()
        return f"{entity_name} already exists or conflicts with an existing record: {detail}"
    if "foreign key constraint failed" in lowered:
        return f"{entity_name} references a missing or protected record."
    if "not null constraint failed" in lowered:
        detail = raw.split(":", maxsplit=1)[-1].strip()
        return f"{entity_name} is missing a required field: {detail}"
    return f"Failed to persist {entity_name}: {raw}"


async def flush_or_409(db: AsyncSession, *, entity_name: str) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_extract_integrity_message(exc, entity_name)) from exc


async def commit_or_409(db: AsyncSession, *, entity_name: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_extract_integrity_message(exc, entity_name)) from exc


async def delete_and_commit_or_409(db: AsyncSession, row, *, entity_name: str) -> None:
    await db.delete(row)
    await commit_or_409(db, entity_name=entity_name)
