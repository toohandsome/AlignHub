import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.entities import ChatSession
from app.routes.common import get_run_manager
from app.runtime import RunManager
from app.schemas import ChatSessionCreate, ChatSessionRead, ChatSessionStartRequest, ChatSessionUpdate, EventRead, ReportRead, RunControlRequest, RunRead, RunUserInputRequest, ToolLogRead
from app.services import (
    commit_or_409,
    delete_and_commit_or_409,
    event_to_read,
    flush_or_409,
    load_session,
    report_to_read,
    run_to_read,
    session_to_read,
    sync_session_agents,
    tool_log_to_read,
)

router = APIRouter()


@router.get("/chat-sessions", response_model=list[ChatSessionRead])
async def list_chat_sessions(db: AsyncSession = Depends(get_db)):
    """查询讨论会话列表。"""
    res = await db.execute(select(ChatSession).options(selectinload(ChatSession.agents)).order_by(ChatSession.created_at.desc()))
    return [session_to_read(item) for item in res.scalars().all()]


@router.post("/chat-sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
async def create_chat_session(payload: ChatSessionCreate, db: AsyncSession = Depends(get_db)):
    """创建讨论会话，并写入参与 Agent 顺序。"""
    row = ChatSession(
        name=payload.name,
        topic=payload.topic,
        max_rounds=payload.max_rounds,
        status=payload.status,
        feishu_chat_id=payload.feishu_chat_id,
        feishu_topic_root_id=payload.feishu_topic_root_id,
        feishu_enabled=payload.feishu_enabled,
    )
    db.add(row)
    await flush_or_409(db, entity_name="chat session")
    try:
        await sync_session_agents(db, row.id, payload.agent_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await commit_or_409(db, entity_name="chat session")
    loaded = await load_session(db, row.id)
    return session_to_read(loaded)


@router.get("/chat-sessions/{session_id}", response_model=ChatSessionRead)
async def get_chat_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """查看单个会话详情。"""
    row = await load_session(db, session_id)
    if not row:
        raise HTTPException(404, "Chat session not found")
    return session_to_read(row)


@router.put("/chat-sessions/{session_id}", response_model=ChatSessionRead)
async def update_chat_session(session_id: str, payload: ChatSessionUpdate, db: AsyncSession = Depends(get_db)):
    """更新会话基础信息和参与 Agent 列表。"""
    row = await load_session(db, session_id)
    if not row:
        raise HTTPException(404, "Chat session not found")
    for key, value in payload.model_dump(exclude_unset=True, exclude={"agent_ids"}).items():
        setattr(row, key, value)
    if payload.agent_ids is not None:
        try:
            await sync_session_agents(db, row.id, payload.agent_ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    await commit_or_409(db, entity_name="chat session")
    loaded = await load_session(db, session_id)
    return session_to_read(loaded)


@router.delete("/chat-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """删除会话。"""
    row = await db.get(ChatSession, session_id)
    if not row:
        raise HTTPException(404, "Chat session not found")
    await delete_and_commit_or_409(db, row, entity_name="chat session")


@router.post("/chat-sessions/{session_id}/start", response_model=RunRead)
async def start_chat_session(
    session_id: str,
    payload: ChatSessionStartRequest | None = None,
    run_manager: RunManager = Depends(get_run_manager),
):
    """启动一次新的讨论运行。"""
    try:
        return run_to_read(await run_manager.start(session_id, notify_feishu=(payload.notify_feishu if payload else True)))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: str, run_manager: RunManager = Depends(get_run_manager)):
    """查询单个 Run。"""
    row = await run_manager.get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return run_to_read(row)


@router.get("/runs", response_model=list[RunRead])
async def list_runs(session_id: str | None = Query(default=None), run_manager: RunManager = Depends(get_run_manager)):
    """列出 Run，可按 session_id 过滤。"""
    return [run_to_read(item) for item in await run_manager.list_runs(session_id=session_id)]


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: str, run_manager: RunManager = Depends(get_run_manager)):
    """删除历史 Run。"""
    try:
        deleted = await run_manager.delete_run(run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Run not found")


@router.post("/runs/{run_id}/stop")
async def stop_run(
    run_id: str,
    payload: RunControlRequest | None = None,
    run_manager: RunManager = Depends(get_run_manager),
):
    """停止运行，并等待最终状态落库。"""
    await run_manager.stop(run_id, source=(payload.source if payload else "user"))
    return {"status": "stopped", "run_id": run_id}


@router.post("/runs/{run_id}/pause", response_model=RunRead)
async def pause_run(run_id: str, payload: RunControlRequest, run_manager: RunManager = Depends(get_run_manager)):
    """暂停运行，并可附带一条补充信息。"""
    try:
        row = await run_manager.pause(run_id, message=payload.message, source=payload.source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not row:
        raise HTTPException(404, "Run not found")
    return run_to_read(row)


@router.post("/runs/{run_id}/resume", response_model=RunRead)
async def resume_run(run_id: str, payload: RunControlRequest, run_manager: RunManager = Depends(get_run_manager)):
    """恢复运行，并可携带恢复说明。"""
    try:
        row = await run_manager.resume(run_id, message=payload.message, source=payload.source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not row:
        raise HTTPException(404, "Run not found")
    return run_to_read(row)


@router.post("/runs/{run_id}/user-input", response_model=RunRead)
async def inject_run_user_input(run_id: str, payload: RunUserInputRequest, run_manager: RunManager = Depends(get_run_manager)):
    """向运行中的会话注入用户补充输入。"""
    try:
        row = await run_manager.inject_user_input(
            run_id,
            message=payload.message,
            source=payload.source,
            pause=payload.pause,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not row:
        raise HTTPException(404, "Run not found")
    return run_to_read(row)


@router.get("/runs/{run_id}/events", response_model=list[EventRead])
async def list_run_events(run_id: str, run_manager: RunManager = Depends(get_run_manager)):
    """查询某个 Run 的事件时间线。"""
    return [event_to_read(item) for item in await run_manager.list_events(run_id)]


@router.get("/runs/{run_id}/report", response_model=ReportRead)
async def get_run_report(run_id: str, run_manager: RunManager = Depends(get_run_manager)):
    """获取 Run 的最终报告。"""
    row = await run_manager.get_report(run_id)
    if not row:
        raise HTTPException(404, "Report not found")
    return report_to_read(row)


@router.get("/runs/{run_id}/tool-logs", response_model=list[ToolLogRead])
async def list_run_tool_logs(run_id: str, run_manager: RunManager = Depends(get_run_manager)):
    """查询 Run 期间的工具调用日志。"""
    return [tool_log_to_read(item) for item in await run_manager.list_tool_logs(run_id)]


@router.websocket("/ws/runs/{run_id}")
async def run_ws(websocket: WebSocket, run_id: str):
    """运行详情页使用的实时事件 WebSocket。"""
    await websocket.accept()
    broker = websocket.app.state.broker
    queue = await broker.subscribe(run_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    finally:
        await broker.unsubscribe(run_id, queue)
