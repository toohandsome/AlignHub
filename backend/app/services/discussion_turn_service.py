from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core import settings
from app.db import SessionLocal
from app.entities import AgentConfig
from app.runtime_common import ModeratorDecision
from app.services.discussion_prompts import (
    build_agent_turn_prompt,
    build_final_report,
    build_moderator_prompt,
    compose_agent_system_prompt,
    shorten_text,
)
from app.services.discussion_state import (
    annotate_patch_log_metrics as _annotate_patch_log_metrics,
    apply_private_tool_updates as _apply_private_tool_updates,
    apply_safe_state_patch_candidates as _apply_safe_state_patch_candidates,
    build_history_message as _build_history_message,
    build_round_summary_record as _build_round_summary_record,
    clean_string_list as _clean_string_list,
    extract_state_patch_proposals as _extract_state_patch_proposals,
    finalize_patch_candidates as _finalize_patch_candidates,
    merge_structured_state as _merge_structured_state,
    merge_unique_items as _merge_unique_items,
    moderator_patch_metrics as _moderator_patch_metrics,
    prepare_private_working_memory as _prepare_private_working_memory,
    resolve_unresolved_conflicts as _resolve_unresolved_conflicts,
    structured_state_preview as _structured_state_preview,
)
from app.services.langgraph_models import build_chat_model
from app.services.langgraph_tools import LangGraphToolFactory
from app.services.run_execution_notifier import RunExecutionNotifier
from app.services.run_persistence import RunPersistenceService

logger = logging.getLogger(__name__)


def _serialize_tool_output_text(text: str) -> dict[str, Any]:
    block = {"type": "text", "text": text}
    return {"chunks": [[block]], "text": text}


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(str(item.get("content", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content or "")


def _extract_last_ai_text(messages: list[BaseMessage] | None) -> str:
    if not messages:
        return ""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _message_text(message)
    return _message_text(messages[-1])


def _build_moderator_summary_text(decision: ModeratorDecision) -> str:
    reason = (decision.reason or "").strip() or "当前讨论结论已由主持人完成裁定。"
    next_focus = (decision.next_focus or "").strip()
    if decision.finished:
        return f"主持人总结：本轮讨论已收敛，可以结束。\n\n裁决原因：{reason}"
    if next_focus:
        return f"主持人总结：本轮讨论暂不结束。\n\n裁决原因：{reason}\n\n下一轮建议聚焦：{next_focus}"
    return f"主持人总结：本轮讨论暂不结束。\n\n裁决原因：{reason}"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    candidates: list[str] = [raw]
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            fenced = "\n".join(lines[1:-1]).strip()
            if fenced.lower().startswith("json"):
                fenced = fenced[4:].lstrip()
            if fenced:
                candidates.append(fenced)

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class DiscussionTurnService:
    def __init__(
        self,
        *,
        persistence: RunPersistenceService,
        notifier: RunExecutionNotifier,
        tool_factory: LangGraphToolFactory | None = None,
    ) -> None:
        self.persistence = persistence
        self.notifier = notifier
        self.tool_factory = tool_factory or LangGraphToolFactory()

    async def agent_turn_node(self, state: dict[str, Any]) -> dict[str, Any]:
        run_id = state["run_id"]
        round_no = state["round_no"]
        agent_id = state["discussion_agent_ids"][state["agent_index"]]
        agent = await self.persistence.load_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")

        private_memory_map = {**state.get("private_working_memory", {})}
        private_memory = _prepare_private_working_memory(
            agent,
            private_memory_map.get(agent.id),
            topic=state["topic"],
            latest_message=state.get("discussion_history", [])[-1] if state.get("discussion_history") else None,
            structured_state=state.get("structured_state"),
        )
        prompt = build_agent_turn_prompt(
            run_id=run_id,
            topic=state["topic"],
            round_no=round_no,
            max_rounds=state["max_rounds"],
            agent_name=agent.name,
            history=state.get("discussion_history", []),
            round_summaries=state.get("round_summaries", []),
            structured_state=state.get("structured_state"),
            private_working_memory=private_memory,
            prompt_token_budget=settings.discussion_agent_prompt_token_budget,
            recent_full_message_count=settings.discussion_recent_full_messages,
            retrieval_item_limit=settings.discussion_history_retrieval_items,
        )
        raw_text, private_tool_updates = await self._invoke_agent_turn(
            agent,
            run_id=run_id,
            workspace_root=state["workspace_root"],
            round_no=round_no,
            prompt=prompt,
        )
        history = list(state.get("discussion_history", []))
        patch_candidates = list(state.get("state_patch_candidates") or [])
        if raw_text:
            message_id = uuid.uuid4().hex
            text, extracted_patches = _extract_state_patch_proposals(
                raw_text,
                round_no=round_no,
                agent_id=agent.id,
                agent_name=agent.name,
                source_message_id=message_id,
            )
            patch_candidates.extend(extracted_patches)
        else:
            message_id = uuid.uuid4().hex
            text = raw_text
        if text:
            history_item = _build_history_message(
                round_no=round_no,
                max_rounds=state.get("max_rounds"),
                agent_id=agent.id,
                agent_name=agent.name,
                text=text,
                message_id=message_id,
            )
            history.append(history_item)
            await self.notifier.publish_message_completed(
                run_id,
                round_no=round_no,
                agent_id=agent.id,
                agent_name=agent.name,
                text=text,
                message_id=message_id,
                metadata={
                    "runtime_engine": "langgraph",
                    "message_kind": history_item.get("message_kind"),
                    "saliency_score": history_item.get("saliency_score"),
                    "state_patch_count": len([patch for patch in patch_candidates if patch.get("source_message_id") == message_id]),
                },
            )
        private_memory_map[agent.id] = _apply_private_tool_updates(
            private_memory,
            tool_updates=private_tool_updates,
        )
        return {
            "discussion_history": history,
            "agent_index": state["agent_index"] + 1,
            "private_working_memory": private_memory_map,
            "state_patch_candidates": patch_candidates[-50:],
        }

    async def force_continue_node(self, state: dict[str, Any]) -> dict[str, Any]:
        premerged_state, pending_patches, patch_log = _apply_safe_state_patch_candidates(state)
        decision = ModeratorDecision(
            finished=False,
            reason=f"At least {state['min_required_rounds']} rounds are required before finishing.",
            next_focus="继续补充关键分歧、证据和风险比较。",
            open_questions=["还有哪些关键分歧、证据或风险没有充分展开？"],
            risks=["若过早结束讨论，可能导致关键分歧尚未充分暴露。"],
        )
        round_summary = _build_round_summary_record(state, decision)
        participant_names = [
            str(item.get("agent_name") or "")
            for item in state.get("discussion_history", [])
            if item.get("agent_name")
        ]
        structured_state = _merge_structured_state(
            premerged_state,
            topic=state["topic"],
            round_no=state["round_no"],
            max_rounds=state["max_rounds"],
            participant_names=participant_names,
            round_summary=round_summary,
        )
        patch_log = _annotate_patch_log_metrics(patch_log)
        structured_state["patch_metrics"] = _moderator_patch_metrics(patch_log)
        await self.notifier.publish_moderator_decision(
            state["run_id"],
            round_no=state["round_no"],
            payload=decision.model_dump(),
            structured_state=_structured_state_preview(structured_state),
        )
        moderator = await self.persistence.load_agent(state["moderator_agent_id"])
        if moderator:
            await self._publish_moderator_summary_message(
                run_id=state["run_id"],
                round_no=state["round_no"],
                moderator=moderator,
                decision=decision,
                decision_source="rule",
            )
        return {
            "round_summaries": [*state.get("round_summaries", []), round_summary],
            "structured_state": structured_state,
            "moderator_decision": decision.model_dump(),
            "finished": False,
            "state_patch_candidates": pending_patches,
            "state_patch_log": patch_log[-80:],
        }

    async def moderator_turn_node(self, state: dict[str, Any]) -> dict[str, Any]:
        moderator = await self.persistence.load_agent(state["moderator_agent_id"])
        if not moderator:
            raise ValueError(f"Moderator not found: {state['moderator_agent_id']}")

        premerged_state, pending_patches, patch_log = _apply_safe_state_patch_candidates(state)
        effective_state = dict(state)
        effective_state["structured_state"] = premerged_state
        effective_state["state_patch_candidates"] = pending_patches
        effective_state["state_patch_log"] = patch_log

        decision = await self._invoke_moderator_turn(moderator, effective_state)
        payload = decision.model_dump()
        round_summary = _build_round_summary_record(effective_state, decision)
        participant_names = [
            str(item.get("agent_name") or "")
            for item in effective_state.get("discussion_history", [])
            if item.get("agent_name")
        ]
        structured_state = _merge_structured_state(
            premerged_state,
            topic=effective_state["topic"],
            round_no=effective_state["round_no"],
            max_rounds=effective_state["max_rounds"],
            participant_names=participant_names,
            round_summary=round_summary,
        )
        remaining_patches, final_patch_log = _finalize_patch_candidates(
            pending_patches,
            structured_state=structured_state,
            round_no=effective_state["round_no"],
        )
        unresolved_conflicts, unresolved_conflict_details, unresolved_patch_log = _resolve_unresolved_conflicts(
            remaining_patches,
            structured_state=structured_state,
            decision_reason=decision.reason,
            round_no=effective_state["round_no"],
        )
        if unresolved_conflicts:
            structured_state["unresolved_conflicts"] = _merge_unique_items(
                structured_state.get("unresolved_conflicts"),
                unresolved_conflicts,
                limit=8,
            )
            structured_state["unresolved_conflict_details"] = unresolved_conflict_details
            conflict_focus = shorten_text(f"优先裁决未解决冲突：{unresolved_conflicts[0]}", 180)
            current_focus = str(structured_state.get("next_focus") or "").strip()
            if conflict_focus and conflict_focus not in current_focus:
                structured_state["next_focus"] = f"{conflict_focus}；{current_focus}" if current_focus else conflict_focus
            remaining_patches = [
                {**item, "status": "unresolved_conflict"} if str(item.get("status") or "") == "conflicted" else item
                for item in remaining_patches
                if str(item.get("status") or "") != "conflicted"
            ]
        combined_patch_log = _annotate_patch_log_metrics([*patch_log, *final_patch_log, *unresolved_patch_log][-80:])
        structured_state["patch_metrics"] = _moderator_patch_metrics(combined_patch_log)
        await self.notifier.publish_moderator_decision(
            effective_state["run_id"],
            round_no=effective_state["round_no"],
            payload=payload,
            structured_state=_structured_state_preview(structured_state),
        )
        await self._publish_moderator_summary_message(
            run_id=effective_state["run_id"],
            round_no=effective_state["round_no"],
            moderator=moderator,
            decision=decision,
            decision_source="model",
        )
        return {
            "round_summaries": [*effective_state.get("round_summaries", []), round_summary],
            "structured_state": structured_state,
            "moderator_decision": payload,
            "finished": bool(decision.finished),
            "state_patch_candidates": remaining_patches,
            "state_patch_log": combined_patch_log,
        }

    async def report_node(self, state: dict[str, Any]) -> dict[str, Any]:
        title, markdown, conclusion = build_final_report(
            session_name=state["session_name"],
            topic=state["topic"],
            history=state.get("discussion_history", []),
            round_summaries=state.get("round_summaries", []),
            structured_state=state.get("structured_state"),
            rounds=state["round_no"],
            per_message_char_limit=settings.report_message_char_limit,
        )
        report = await self.persistence.save_report(
            state["run_id"],
            title=title,
            summary_markdown=markdown,
            conclusion_json=conclusion,
        )
        await self.notifier.publish_report_generated(state["run_id"], report=report)
        await self.persistence.persist_run_state(
            state["run_id"],
            status="finished",
            session_status="finished",
            ended=True,
        )
        await self.notifier.publish_finished(state["run_id"])
        return {"finished": True}

    async def ask_agent_in_session(self, session_id: str, agent_name: str, question: str) -> dict[str, Any]:
        async with SessionLocal() as db:
            session = await self.persistence.load_session_for_reply(db, session_id)
            if not session:
                raise ValueError("Chat session not found")
            links = sorted(session.agents, key=lambda item: item.speak_order)
            matched = next(
                (
                    link.agent
                    for link in links
                    if link.agent.name == agent_name or link.agent.name.lower() == agent_name.lower()
                ),
                None,
            )
            if not matched:
                raise ValueError(f"Agent not found in session: {agent_name}")

        provider = matched.model.provider
        prompt = (
            f"当前会话主题：{session.topic}\n"
            f"用户正在飞书群中单独向你提问。请只以“{matched.name}”的角色口吻直接回答，简洁且可执行。\n\n"
            f"用户问题：{question}"
        )
        if provider.provider_type == "mock":
            text = self._mock_agent_reply(prompt)
        else:
            model = build_chat_model(provider, matched.model)

            async def noop_started(tool_call_id: str, tool_name: str, tool_input: dict[str, Any]) -> None:
                return None

            async def noop_finished(tool_call_id: str, tool_name: str, tool_input: dict[str, Any], output_text: str) -> None:
                return None

            async def noop_failed(tool_call_id: str, tool_name: str, tool_input: dict[str, Any], exc: Exception) -> None:
                return None

            tools = self.tool_factory.build_tools(
                matched,
                run_id="feishu-direct",
                workspace_root=settings.workspace_root,
                round_no_getter=lambda: 0,
                on_tool_started=noop_started,
                on_tool_finished=noop_finished,
                on_tool_failed=noop_failed,
            )
            executor = create_agent(
                model=model,
                tools=tools,
                system_prompt=compose_agent_system_prompt(
                    matched,
                    skill_char_limit=settings.skill_prompt_char_limit,
                    skill_total_char_limit=settings.skill_prompt_total_char_limit,
                ),
                debug=settings.langgraph_debug,
            )
            result = await executor.ainvoke({"messages": [("user", prompt)]})
            text = _extract_last_ai_text(result.get("messages"))
        return {"agent_id": matched.id, "agent_name": matched.name, "text": text}

    async def _tool_started(self, run_id: str, round_no: int, agent_id: str, tool_call_id: str, tool_name: str, tool_input: dict[str, Any]) -> None:
        await self.persistence.create_tool_log(
            run_id=run_id,
            round_no=round_no,
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        await self.notifier.publish_tool_started(
            run_id,
            round_no=round_no,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
        )

    async def _tool_finished(self, run_id: str, round_no: int, agent_id: str, tool_call_id: str, tool_name: str, tool_input: dict[str, Any], output_text: str) -> None:
        serialized = _serialize_tool_output_text(output_text)
        await self.persistence.complete_tool_log(run_id=run_id, tool_call_id=tool_call_id, tool_output=serialized)
        await self.notifier.publish_tool_completed(
            run_id,
            round_no=round_no,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            output_chunk=serialized["chunks"][0],
        )

    async def _tool_failed(self, run_id: str, round_no: int, agent_id: str, tool_call_id: str, tool_name: str, tool_input: dict[str, Any], exc: Exception) -> None:
        error_payload = {"error": str(exc), "type": type(exc).__name__}
        await self.persistence.fail_tool_log(run_id=run_id, tool_call_id=tool_call_id, error_payload=error_payload)
        await self.notifier.publish_tool_failed(
            run_id,
            round_no=round_no,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            error_payload=error_payload,
        )

    async def _invoke_agent_turn(self, agent: AgentConfig, *, run_id: str, workspace_root: str, round_no: int, prompt: str) -> tuple[str, list[dict[str, Any]]]:
        private_tool_updates: list[dict[str, Any]] = []

        async def on_started(tool_call_id: str, tool_name: str, tool_input: dict[str, Any]) -> None:
            await self._tool_started(run_id, round_no, agent.id, tool_call_id, tool_name, tool_input)

        async def on_finished(tool_call_id: str, tool_name: str, tool_input: dict[str, Any], output_text: str) -> None:
            private_tool_updates.append(
                {
                    "tool_name": tool_name,
                    "status": "completed",
                    "summary": shorten_text(output_text, 180),
                    "round_no": round_no,
                }
            )
            await self._tool_finished(run_id, round_no, agent.id, tool_call_id, tool_name, tool_input, output_text)

        async def on_failed(tool_call_id: str, tool_name: str, tool_input: dict[str, Any], exc: Exception) -> None:
            private_tool_updates.append(
                {
                    "tool_name": tool_name,
                    "status": "failed",
                    "summary": shorten_text(str(exc), 180),
                    "round_no": round_no,
                }
            )
            await self._tool_failed(run_id, round_no, agent.id, tool_call_id, tool_name, tool_input, exc)

        tools = self.tool_factory.build_tools(
            agent,
            run_id=run_id,
            workspace_root=workspace_root,
            round_no_getter=lambda: round_no,
            on_tool_started=on_started,
            on_tool_finished=on_finished,
            on_tool_failed=on_failed,
        )
        provider = agent.model.provider
        if provider.provider_type == "mock":
            return await self._invoke_mock_agent_turn(prompt=prompt, tools=tools), private_tool_updates

        model = build_chat_model(provider, agent.model)
        executor = create_agent(
            model=model,
            tools=tools,
            system_prompt=compose_agent_system_prompt(
                agent,
                skill_char_limit=settings.skill_prompt_char_limit,
                skill_total_char_limit=settings.skill_prompt_total_char_limit,
            ),
            debug=settings.langgraph_debug,
        )
        result = await executor.ainvoke({"messages": [("user", prompt)]})
        return _extract_last_ai_text(result.get("messages")), private_tool_updates

    async def _invoke_moderator_turn(self, moderator: AgentConfig, state: dict[str, Any]) -> ModeratorDecision:
        provider = moderator.model.provider
        prompt = build_moderator_prompt(
            run_id=state["run_id"],
            topic=state["topic"],
            round_no=state["round_no"],
            max_rounds=state["max_rounds"],
            history=state.get("discussion_history", []),
            round_summaries=state.get("round_summaries", []),
            structured_state=state.get("structured_state"),
            state_patch_candidates=state.get("state_patch_candidates", []),
            prompt_token_budget=settings.discussion_moderator_prompt_token_budget,
            recent_full_message_count=max(settings.discussion_recent_full_messages, 8),
            retrieval_item_limit=max(settings.discussion_history_retrieval_items, 8),
        )
        if provider.provider_type == "mock":
            return self._mock_moderator_decision(state)

        model = build_chat_model(provider, moderator.model)
        system_prompt = (
            f"{compose_agent_system_prompt(moderator, skill_char_limit=settings.skill_prompt_char_limit, skill_total_char_limit=settings.skill_prompt_total_char_limit)}\n\n"
            "你当前扮演讨论主持人。"
            "你需要综合公开讨论历史、结构化状态和待审补丁提案，"
            "判断讨论是否可以结束，并输出结构化裁决结果。"
            "请重点补全 finished/reason/next_focus，并尽量给出 key_points、agreements、disagreements、open_questions、candidate_options、risks。"
            "请只返回 JSON，不要输出 Markdown 或额外说明。"
        )
        timeout_seconds = max(5, int(settings.langgraph_moderator_timeout_seconds))
        try:
            result = await asyncio.wait_for(
                model.ainvoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=prompt),
                    ]
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Moderator model timed out after %ss for run=%s provider=%s model=%s; falling back to local decision",
                timeout_seconds,
                state["run_id"],
                provider.name,
                moderator.model.model_name,
            )
            return ModeratorDecision(
                finished=state["round_no"] >= state["max_rounds"],
                reason=f"Moderator timed out after {timeout_seconds}s; fallback decision applied locally.",
                next_focus=None if state["round_no"] >= state["max_rounds"] else "继续补充尚未验证的分歧、证据与风险。",
                open_questions=[] if state["round_no"] >= state["max_rounds"] else ["还有哪些关键分歧、证据或风险需要继续验证？"],
                risks=["主持人超时，当前结果来自本地回退逻辑，可能遗漏更细粒度判断。"],
            )

        return self.parse_moderator_decision(_message_text(result), state)

    def parse_moderator_decision(self, raw_text: str, state: dict[str, Any]) -> ModeratorDecision:
        payload = _extract_json_object(raw_text) or {}
        finished_raw = payload.get("finished")
        if isinstance(finished_raw, bool):
            finished = finished_raw
        elif isinstance(finished_raw, (int, float)):
            finished = bool(finished_raw)
        elif isinstance(finished_raw, str):
            finished = finished_raw.strip().lower() in {"true", "1", "yes", "y"}
        else:
            finished = state["round_no"] >= state["max_rounds"]

        reason = str(payload.get("reason") or "").strip()
        next_focus_value = payload.get("next_focus")
        next_focus = str(next_focus_value).strip() if next_focus_value not in {None, ""} else None

        if not reason:
            fallback_reason = raw_text or "Moderator fallback decision"
            reason = shorten_text(fallback_reason, 200)
        if not finished and not next_focus:
            next_focus = "继续补充尚未收敛的分歧、证据与风险。"

        key_points = _clean_string_list(payload.get("key_points"), limit=6)
        agreements = _clean_string_list(payload.get("agreements"), limit=6)
        disagreements = _clean_string_list(payload.get("disagreements"), limit=6)
        open_questions = _clean_string_list(payload.get("open_questions"), limit=6)
        candidate_options = _clean_string_list(payload.get("candidate_options"), limit=6)
        risks = _clean_string_list(payload.get("risks"), limit=6)
        if not finished and next_focus and next_focus not in open_questions:
            open_questions.append(next_focus)

        return ModeratorDecision(
            finished=finished,
            reason=reason,
            next_focus=None if finished else next_focus,
            key_points=key_points,
            agreements=agreements,
            disagreements=disagreements,
            open_questions=open_questions,
            candidate_options=candidate_options,
            risks=risks,
        )

    async def _publish_moderator_summary_message(self, *, run_id: str, round_no: int, moderator: AgentConfig, decision: ModeratorDecision, decision_source: str) -> None:
        await self.notifier.publish_message_completed(
            run_id,
            round_no=round_no,
            agent_id=moderator.id,
            agent_name=moderator.name,
            text=_build_moderator_summary_text(decision),
            metadata={
                "runtime_engine": "langgraph",
                "message_kind": "moderator_summary",
                "decision_source": decision_source,
            },
        )

    def _mock_agent_reply(self, prompt: str) -> str:
        return (
            "我建议优先选择模块化、可审计、易扩展的实现路径。\n\n"
            f"结合当前上下文：{shorten_text(prompt, 220) or '暂无更多上下文。'}"
        )

    async def _invoke_mock_agent_turn(self, *, prompt: str, tools: list[Any]) -> str:
        if settings.langgraph_mock_response_delay_ms > 0:
            await asyncio.sleep(settings.langgraph_mock_response_delay_ms / 1000)
        tool_note = ""
        preferred_order = [
            "topic_probe",
            "list_files",
            "read_file",
            "git_status",
            "git_diff",
            "git_log",
            "write_file",
            "edit_file",
            "git_add",
            "git_commit",
        ]
        tool_map = {tool.name: tool for tool in tools}
        chosen = next((tool_map[name] for name in preferred_order if name in tool_map), tools[0] if tools else None)
        if chosen is not None:
            tool_input = self._build_mock_tool_input(chosen.name, prompt)
            output = await chosen.ainvoke(tool_input)
            tool_note = shorten_text(str(output or ""), 220)

        base = "我建议优先选择模块化、可审计、易扩展的实现路径。"
        if tool_note:
            base = f"基于工具验证结果，我建议优先选择模块化、可审计、易扩展的实现路径。工具摘要：{tool_note}"
        return f"{base}\n\n结合当前上下文：{shorten_text(prompt, 220) or '暂无更多上下文。'}"

    def _build_mock_tool_input(self, tool_name: str, prompt: str) -> dict[str, Any]:
        if tool_name == "topic_probe":
            return {"topic": shorten_text(prompt, 200) or "请分析当前主题"}
        if tool_name == "list_files":
            return {"path": ".", "recursive": False, "limit": 20}
        if tool_name == "read_file":
            return {"path": "README.md", "start_line": 1, "end_line": 40}
        if tool_name == "write_file":
            return {"path": "mock_notes.txt", "content": "mock generated content", "overwrite": True}
        if tool_name == "edit_file":
            return {
                "path": "mock_notes.txt",
                "old_text": "mock generated content",
                "new_text": "mock updated content",
                "replace_all": False,
            }
        if tool_name == "git_status":
            return {}
        if tool_name == "git_log":
            return {"limit": 5}
        if tool_name == "git_diff":
            return {"pathspec": ""}
        if tool_name == "git_add":
            return {"pathspec": "."}
        if tool_name == "git_commit":
            return {"message": "mock commit"}
        if tool_name.startswith("mcp_"):
            return {"action": "ping", "payload_json": "{}"}
        return {}

    def _mock_moderator_decision(self, state: dict[str, Any]) -> ModeratorDecision:
        round_no = state["round_no"]
        max_rounds = min(state["max_rounds"], settings.mock_discussion_round_cap)
        finished = round_no >= max_rounds
        return ModeratorDecision(
            finished=finished,
            reason="mock moderator decided based on configured round cap",
            next_focus=None if finished else "继续比较方案可执行性与风险",
            key_points=[f"Mock moderator evaluated round {round_no} against configured cap {max_rounds}."],
            agreements=["轮次推进正常。"] if finished else [],
            open_questions=[] if finished else ["需要继续比较方案可执行性与风险。"],
            risks=["当前结果来自 mock 主持人规则，不代表真实模型裁决。"],
        )
