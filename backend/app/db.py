from __future__ import annotations

from collections.abc import AsyncGenerator
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类。"""
    pass


engine = create_async_engine(
    settings.database_url,
    future=True,
    echo=False,
    connect_args={"timeout": 30},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """为每个请求提供一个独立的异步数据库会话。"""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """启动时初始化数据库表结构与必要索引。"""
    from app import entities  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_sqlite_columns(conn)


async def _ensure_sqlite_columns(conn: AsyncConnection) -> None:
    """对 SQLite 做轻量级结构补齐。

    这里承担的是“向后兼容历史本地数据库”的职责：
    - 打开 WAL 等运行时优化
    - 检查关键列是否存在
    - 增补索引和活动 Run 约束
    """
    await conn.execute(text("PRAGMA journal_mode=WAL"))
    await conn.execute(text("PRAGMA synchronous=NORMAL"))

    async def has_column(table: str, column: str) -> bool:
        """检查某张表是否已经包含目标列。"""
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in result.fetchall())

    statements: list[str] = []

    if not await has_column("skill_definitions", "source_type"):
        statements.append("ALTER TABLE skill_definitions ADD COLUMN source_type VARCHAR(32) DEFAULT 'manual'")
    if not await has_column("skill_definitions", "package_path"):
        statements.append("ALTER TABLE skill_definitions ADD COLUMN package_path TEXT")
    if not await has_column("skill_definitions", "entry_file"):
        statements.append("ALTER TABLE skill_definitions ADD COLUMN entry_file TEXT")
    if not await has_column("mcp_server_configs", "jar_path"):
        statements.append("ALTER TABLE mcp_server_configs ADD COLUMN jar_path TEXT")
    if not await has_column("chat_sessions", "feishu_chat_id"):
        statements.append("ALTER TABLE chat_sessions ADD COLUMN feishu_chat_id VARCHAR(128)")
    if not await has_column("chat_sessions", "feishu_topic_root_id"):
        statements.append("ALTER TABLE chat_sessions ADD COLUMN feishu_topic_root_id VARCHAR(128)")
    if not await has_column("chat_sessions", "feishu_enabled"):
        statements.append("ALTER TABLE chat_sessions ADD COLUMN feishu_enabled BOOLEAN DEFAULT 0")
    if not await has_column("discussion_runs", "notify_feishu"):
        statements.append("ALTER TABLE discussion_runs ADD COLUMN notify_feishu BOOLEAN DEFAULT 1")
    if not await has_column("tool_call_logs", "call_id"):
        statements.append("ALTER TABLE tool_call_logs ADD COLUMN call_id VARCHAR(128)")

    for stmt in statements:
        await conn.execute(text(stmt))

    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_sessions_feishu_binding ON chat_sessions(feishu_chat_id, feishu_topic_root_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_discussion_runs_session_status_created ON discussion_runs(session_id, status, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tool_call_logs_run_started ON tool_call_logs(run_id, started_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tool_call_logs_run_call_id ON tool_call_logs(run_id, call_id)"))
    try:
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_feishu_topic
                ON chat_sessions(feishu_chat_id, feishu_topic_root_id)
                WHERE feishu_chat_id IS NOT NULL
                  AND feishu_topic_root_id IS NOT NULL
                """,
            )
        )
    except Exception as exc:
        logger.warning("Skipping unique topic binding index for chat_sessions: %s", exc)
    try:
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_discussion_runs_active_session
                ON discussion_runs(session_id)
                WHERE status IN ('draft', 'running', 'paused')
                """,
            )
        )
    except Exception as exc:
        logger.warning("Skipping active-run unique index for discussion_runs: %s", exc)
