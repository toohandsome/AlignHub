from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import DatabaseError, IntegrityError
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


def _extract_database_message(exc: DatabaseError, entity_name: str) -> str:
    raw = str(getattr(exc, "orig", exc))
    lowered = raw.lower()
    if "database disk image is malformed" in lowered:
        return (
            f"{entity_name} failed because the SQLite database file is corrupted. "
            "Please back up the current backend.db and rebuild or recover it before retrying."
        )
    if "database is locked" in lowered:
        return f"{entity_name} failed because the database is locked by another operation."
    return f"Database error while processing {entity_name}: {raw}"


def database_error_to_http_exception(exc: DatabaseError, *, entity_name: str) -> HTTPException:
    return HTTPException(status_code=500, detail=_extract_database_message(exc, entity_name))


async def flush_or_409(db: AsyncSession, *, entity_name: str) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_extract_integrity_message(exc, entity_name)) from exc
    except DatabaseError as exc:
        await db.rollback()
        raise database_error_to_http_exception(exc, entity_name=entity_name) from exc


async def commit_or_409(db: AsyncSession, *, entity_name: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_extract_integrity_message(exc, entity_name)) from exc
    except DatabaseError as exc:
        await db.rollback()
        raise database_error_to_http_exception(exc, entity_name=entity_name) from exc


async def delete_and_commit_or_409(db: AsyncSession, row, *, entity_name: str) -> None:
    try:
        await db.delete(row)
    except DatabaseError as exc:
        await db.rollback()
        raise database_error_to_http_exception(exc, entity_name=entity_name) from exc
    await commit_or_409(db, entity_name=entity_name)
