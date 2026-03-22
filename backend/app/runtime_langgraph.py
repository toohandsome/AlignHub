from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.core import settings
from app.db import SessionLocal
from app.entities import DiscussionEvent, DiscussionRun, FinalReport, ToolCallLog
from app.runtime_common import EventService, ModeratorDecision, RunControlState
from app.services.context_retrieval import purge_run_chunks
from app.services.discussion_state import (
    annotate_patch_log_metrics as _annotate_patch_log_metrics,
    apply_safe_state_patch_candidates as _apply_safe_state_patch_candidates,
    apply_semantic_ttl as _apply_semantic_ttl,
    build_agent_analysis_preferences as _build_agent_analysis_preferences,
    build_history_message as _build_history_message,
    extract_state_patch_proposals as _extract_state_patch_proposals,
    finalize_patch_candidates as _finalize_patch_candidates,
    group_patch_conflicts as _group_patch_conflicts,
    moderator_patch_metrics as _moderator_patch_metrics,
    pin_user_focus_point as _pin_user_focus_point,
    resolve_unresolved_conflicts as _resolve_unresolved_conflicts,
)
from app.services.discussion_turn_service import (
    DiscussionTurnService,
    _build_moderator_summary_text,
    _extract_json_object,
)
from app.services.run_execution_notifier import RunExecutionNotifier
from app.services.run_lifecycle import RunLifecycleService
from app.services.run_persistence import RunPersistenceService
from app.services.workspace import cleanup_run_workspace_async, prepare_run_workspace_async



class DiscussionState(TypedDict, total=False):
    run_id: str
    session_id: str
    session_name: str
    topic: str
    max_rounds: int
    min_required_rounds: int
    round_no: int
    agent_index: int
    discussion_agent_ids: list[str]
    moderator_agent_id: str
    discussion_history: list[dict[str, Any]]
    round_summaries: list[dict[str, Any]]
    structured_state: dict[str, Any]
    private_working_memory: dict[str, dict[str, Any]]
    state_patch_candidates: list[dict[str, Any]]
    state_patch_log: list[dict[str, Any]]
    workspace_root: str
    finished: bool
    moderator_decision: dict[str, Any] | None


class DiscussionEngine:
    def __init__(
        self,
        event_service: EventService,
        persistence: RunPersistenceService | None = None,
        notifier: RunExecutionNotifier | None = None,
    ) -> None:
        self.persistence = persistence or RunPersistenceService()
        self.notifier = notifier or RunExecutionNotifier(event_service)
        self.turn_service = DiscussionTurnService(
            persistence=self.persistence,
            notifier=self.notifier,
        )
        self._controls: dict[str, RunControlState] = {}
        self._checkpointer_cm: Any | None = None
        self._checkpointer: AsyncSqliteSaver | None = None
        self._graph: Any | None = None
        self._shutdown_requested = False

    def control(self, run_id: str) -> RunControlState:
        if run_id not in self._controls:
            self._controls[run_id] = RunControlState(on_change=lambda snapshot, _run_id=run_id: self._persist_control_state(_run_id, snapshot))
        return self._controls[run_id]

    def clear_control(self, run_id: str) -> None:
        self._controls.pop(run_id, None)

    async def startup(self) -> None:
        self._shutdown_requested = False
        if self._graph is not None:
            return
        checkpoint_path = Path(settings.langgraph_checkpoint_path).resolve()
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
        self._checkpointer = await self._checkpointer_cm.__aenter__()
        self._graph = self._build_graph()

    async def shutdown(self) -> None:
        self._shutdown_requested = True
        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(None, None, None)
        self._checkpointer_cm = None
        self._checkpointer = None
        self._graph = None

    async def restore_control(self, run_id: str, snapshot: dict[str, Any] | None) -> RunControlState:
        control = self.control(run_id)
        await control.restore_snapshot(snapshot)
        return control

    def _graph_config(self, run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}

    def _build_graph(self):
        if self._checkpointer is None:
            raise RuntimeError("LangGraph checkpointer is not initialized")
        graph = StateGraph(DiscussionState)
        graph.add_node("round_start", self._round_start_node)
        graph.add_node("pause_gate", self._pause_gate_node)
        graph.add_node("inject_inputs", self._inject_inputs_node)
        graph.add_node("agent_turn", self._agent_turn_node)
        graph.add_node("force_continue", self._force_continue_node)
        graph.add_node("moderator_turn", self._moderator_turn_node)
        graph.add_node("next_round", self._next_round_node)
        graph.add_node("report", self._report_node)

        graph.add_edge(START, "round_start")
        graph.add_edge("round_start", "pause_gate")
        graph.add_edge("pause_gate", "inject_inputs")
        graph.add_conditional_edges(
            "inject_inputs",
            self._route_after_inputs,
            {
                "agent_turn": "agent_turn",
                "force_continue": "force_continue",
                "moderator_turn": "moderator_turn",
            },
        )
        graph.add_edge("agent_turn", "pause_gate")
        graph.add_edge("force_continue", "next_round")
        graph.add_conditional_edges(
            "moderator_turn",
            self._route_after_moderator,
            {
                "next_round": "next_round",
                "report": "report",
            },
        )
        graph.add_edge("next_round", "round_start")
        graph.add_edge("report", END)
        return graph.compile(checkpointer=self._checkpointer)

    async def _persist_control_state(self, run_id: str, snapshot: dict[str, Any]) -> None:
        await self.persistence.persist_control_state(run_id, snapshot)

    async def clear_persisted_control_state(self, run_id: str) -> None:
        await self.persistence.clear_persisted_control_state(run_id)

    async def graph_state(self, run_id: str) -> Any:
        if self._graph is None:
            raise RuntimeError("LangGraph runtime is not started")
        return await self._graph.aget_state(self._graph_config(run_id))

    async def _persist_run_state(
        self,
        run_id: str,
        *,
        status: str,
        session_status: str | None = None,
        stop_reason: str | None = None,
        ended: bool = False,
    ) -> None:
        await self.persistence.persist_run_state(
            run_id,
            status=status,
            session_status=session_status,
            stop_reason=stop_reason,
            ended=ended,
        )

    async def _is_terminal_run(self, run_id: str) -> bool:
        return await self.persistence.is_terminal_run(run_id)

    async def _load_run(self, db: AsyncSession, run_id: str) -> DiscussionRun | None:
        return await self.persistence.load_run(db, run_id)

    def _initial_state(self, run: DiscussionRun, workspace_root: str) -> DiscussionState:
        links = sorted(run.session.agents, key=lambda item: item.speak_order)
        ordered_agents = [link.agent for link in links]
        if not ordered_agents:
            raise ValueError("Chat session has no agents")

        moderator_agent = next((agent for agent in ordered_agents if agent.is_moderator), None) or ordered_agents[0]
        discussion_agents = [agent for agent in ordered_agents if agent.id != moderator_agent.id] or [moderator_agent]

        return {
            "run_id": run.id,
            "session_id": run.session_id,
            "session_name": run.session.name,
            "topic": run.session.topic,
            "max_rounds": run.session.max_rounds,
            "min_required_rounds": min(settings.min_discussion_rounds, run.session.max_rounds),
            "round_no": 1,
            "agent_index": 0,
            "discussion_agent_ids": [agent.id for agent in discussion_agents],
            "moderator_agent_id": moderator_agent.id,
            "discussion_history": [],
            "round_summaries": [],
            "structured_state": {
                "topic": run.session.topic,
                "rounds_completed": 0,
                "participant_names": [agent.name for agent in ordered_agents],
                "latest_decision": "in_progress",
                "latest_decision_reason": "",
                "next_focus": None,
                "agreements": [],
                "open_questions": [],
                "candidate_options": [],
                "risks": [],
                "recent_key_points": [],
                "last_round_summary": "",
                "agreement_items": [],
                "open_question_items": [],
                "candidate_option_items": [],
                "risk_items": [],
                "user_pinned_points": [],
                "unresolved_conflicts": [],
                "unresolved_conflict_details": [],
                "patch_metrics": {
                    "moderator_patch_decisions": 0,
                    "moderator_patch_adopted": 0,
                    "moderator_adoption_rate": None,
                    "by_agent": [],
                    "by_field": [],
                },
            },
            "private_working_memory": {
                agent.id: {
                    "draft_notes": [],
                    "tool_result_cache": [],
                    "current_focus": [],
                    "analysis_preferences": _build_agent_analysis_preferences(agent),
                }
                for agent in ordered_agents
            },
            "state_patch_candidates": [],
            "state_patch_log": [],
            "workspace_root": workspace_root,
            "finished": False,
            "moderator_decision": None,
        }
    async def _round_start_node(self, state: DiscussionState) -> dict[str, Any]:
        run_id = state["run_id"]
        round_no = state["round_no"]
        await self.persistence.update_current_round(run_id, round_no)
        await self.notifier.publish_round_started(run_id, round_no=round_no)
        return {}

    async def _pause_gate_node(self, state: DiscussionState) -> dict[str, Any]:
        run_id = state["run_id"]
        round_no = state["round_no"]
        control = self.control(run_id)
        if not await control.is_paused():
            return {}

        pause_source = await control.consume_pause_source() or "user"
        await self._persist_run_state(run_id, status="paused", session_status="paused")
        await self.notifier.publish_paused(run_id, round_no=round_no, source=pause_source)
        for item in await control.mark_inputs_announced():
            await self.notifier.publish_user_input(
                run_id,
                round_no=round_no,
                text=item.text,
                source=item.source,
                mark_important=item.mark_important,
            )
        interrupt({"kind": "pause", "run_id": run_id, "round_no": round_no, "source": pause_source})
        return {}

    async def _inject_inputs_node(self, state: DiscussionState) -> dict[str, Any]:
        run_id = state["run_id"]
        round_no = state["round_no"]
        control = self.control(run_id)
        pending = await control.drain_inputs()
        if not pending:
            return {}
        history = list(state.get("discussion_history", []))
        structured_state = dict(state.get("structured_state") or {})
        for item in pending:
            history_item = _build_history_message(
                round_no=round_no,
                max_rounds=state.get("max_rounds"),
                agent_id="user",
                agent_name="用户补充",
                text=item.text,
                message_kind="user_input",
                explicit_saliency_score=2.5 if item.mark_important else None,
                human_priority="pinned" if item.mark_important else None,
            )
            history.append(
                history_item
            )
            if item.mark_important:
                structured_state = _pin_user_focus_point(structured_state, item.text)
            if not item.announced:
                await self.notifier.publish_user_input(
                    run_id,
                    round_no=round_no,
                    text=item.text,
                    source=item.source,
                    mark_important=item.mark_important,
                )
        return {"discussion_history": history, "structured_state": structured_state}

    def _route_after_inputs(self, state: DiscussionState) -> str:
        if state["agent_index"] < len(state["discussion_agent_ids"]):
            return "agent_turn"
        if state["round_no"] < state["min_required_rounds"]:
            return "force_continue"
        return "moderator_turn"

    async def _agent_turn_node(self, state: DiscussionState) -> dict[str, Any]:
        return await self.turn_service.agent_turn_node(state)

    async def _force_continue_node(self, state: DiscussionState) -> dict[str, Any]:
        return await self.turn_service.force_continue_node(state)

    async def _moderator_turn_node(self, state: DiscussionState) -> dict[str, Any]:
        return await self.turn_service.moderator_turn_node(state)

    def _route_after_moderator(self, state: DiscussionState) -> str:
        if state.get("finished"):
            return "report"
        if state["round_no"] >= state["max_rounds"]:
            return "report"
        return "next_round"

    async def _next_round_node(self, state: DiscussionState) -> dict[str, Any]:
        return {
            "round_no": state["round_no"] + 1,
            "agent_index": 0,
            "moderator_decision": None,
        }

    async def _report_node(self, state: DiscussionState) -> dict[str, Any]:
        return await self.turn_service.report_node(state)

    def _parse_moderator_decision(self, raw_text: str, state: DiscussionState) -> ModeratorDecision:
        return self.turn_service.parse_moderator_decision(raw_text, state)

    async def execute(self, run_id: str, command: Command | None = None, *, continue_from_checkpoint: bool = False) -> None:
        if self._graph is None:
            await self.startup()
        control = self.control(run_id)
        workspace_root = await prepare_run_workspace_async(run_id)
        try:
            payload: DiscussionState | Command | None
            if command is None and not continue_from_checkpoint:
                async with SessionLocal() as db:
                    run = await self._load_run(db, run_id)
                    if not run:
                        raise ValueError("Run not found")
                    payload = self._initial_state(run, workspace_root)
                if not await self.persistence.mark_run_running(run_id, ensure_started_at=True):
                    raise ValueError("Run not found")
                await self.notifier.publish_running(run_id)
            elif command is None:
                if not await self.persistence.mark_run_running(run_id):
                    raise ValueError("Run not found")
                payload = None
            else:
                payload = command

            result = await self._graph.ainvoke(payload, config=self._graph_config(run_id))
            if isinstance(result, dict) and result.get("__interrupt__"):
                return
        except asyncio.CancelledError:
            if self._shutdown_requested:
                raise
            await self._persist_run_state(run_id, status="stopped", session_status="stopped", stop_reason="Stopped by user", ended=True)
            stop_source = await control.consume_stop_source(default="user")
            await self.notifier.publish_stopped(run_id, source=stop_source)
            raise
        except Exception as exc:
            await self._persist_run_state(run_id, status="failed", session_status="failed", stop_reason=str(exc), ended=True)
            await self.notifier.publish_error(run_id, message=str(exc))
            raise
        finally:
            if await self._is_terminal_run(run_id):
                await control.clear_runtime_state()
                await self.clear_persisted_control_state(run_id)
                self.clear_control(run_id)
                await asyncio.to_thread(purge_run_chunks, run_id)
                if settings.cleanup_run_workspace_on_finish:
                    await cleanup_run_workspace_async(run_id)

    async def ask_agent_in_session(self, session_id: str, agent_name: str, question: str) -> dict[str, Any]:
        return await self.turn_service.ask_agent_in_session(session_id, agent_name, question)


class RunManager:
    def __init__(self, event_service: EventService) -> None:
        self.persistence = RunPersistenceService()
        self.notifier = RunExecutionNotifier(event_service)
        self.engine = DiscussionEngine(event_service, persistence=self.persistence, notifier=self.notifier)
        self.lifecycle = RunLifecycleService(
            event_service=event_service,
            engine=self.engine,
            persistence=self.persistence,
        )
        self._tasks = self.lifecycle._tasks
        self._session_start_locks = self.lifecycle._session_start_locks

    async def startup(self) -> None:
        await self.lifecycle.startup()

    async def shutdown(self) -> None:
        await self.lifecycle.shutdown()

    async def recover_active_runs(self) -> list[str]:
        return await self.lifecycle.recover_active_runs()

    async def start(self, session_id: str, *, notify_feishu: bool = True) -> DiscussionRun:
        return await self.lifecycle.start(session_id, notify_feishu=notify_feishu)

    async def stop(self, run_id: str, *, source: str = "user") -> None:
        await self.lifecycle.stop(run_id, source=source)

    async def pause(self, run_id: str, *, message: str | None = None, source: str = "user", mark_important: bool = False) -> DiscussionRun | None:
        return await self.lifecycle.pause(run_id, message=message, source=source, mark_important=mark_important)

    async def resume(self, run_id: str, *, message: str | None = None, source: str = "user", mark_important: bool = False) -> DiscussionRun | None:
        return await self.lifecycle.resume(run_id, message=message, source=source, mark_important=mark_important)

    async def inject_user_input(self, run_id: str, *, message: str, source: str = "user", pause: bool = False, mark_important: bool = False) -> DiscussionRun | None:
        return await self.lifecycle.inject_user_input(
            run_id,
            message=message,
            source=source,
            pause=pause,
            mark_important=mark_important,
        )

    async def get_run(self, run_id: str) -> DiscussionRun | None:
        return await self.lifecycle.get_run(run_id)

    async def find_active_run_for_session(self, session_id: str) -> DiscussionRun | None:
        return await self.lifecycle.find_active_run_for_session(session_id)

    async def list_runs(self, *, session_id: str | None = None) -> list[DiscussionRun]:
        return await self.lifecycle.list_runs(session_id=session_id)

    async def delete_run(self, run_id: str) -> bool:
        return await self.lifecycle.delete_run(run_id)

    async def list_events(self, run_id: str) -> list[DiscussionEvent]:
        return await self.lifecycle.list_events(run_id)

    async def get_report(self, run_id: str) -> FinalReport | None:
        return await self.lifecycle.get_report(run_id)

    async def list_tool_logs(self, run_id: str) -> list[ToolCallLog]:
        return await self.lifecycle.list_tool_logs(run_id)

    async def ask_agent_in_session(self, session_id: str, agent_name: str, question: str) -> dict[str, Any]:
        return await self.lifecycle.ask_agent_in_session(session_id, agent_name, question)
