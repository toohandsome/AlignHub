"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AgentAvatar, EventFilterPanel, JsonDetails } from "@/components/discussion-ui";
import { Badge, Card, CheckboxRow, EmptyState, InlineAlert, PrimaryButton, SecondaryButton, SectionTitle, Skeleton, Textarea, useToast } from "@/components/ui";
import { api, ChatSession, DiscussionEvent, DiscussionRun, FinalReport, ToolCallLog, wsUrl } from "@/lib/api";
import {
  EventFilterKey,
  buildAgentDirectory,
  eventTypeLabel,
  isEventVisible,
  latestStructuredStatePreview,
  resolveAgentDisplay,
  summarizeEvent
} from "@/lib/discussion";
import { formatDateTime, normalizePayload, useRunBundle } from "@/lib/run-bundle";

const RunSessionOverview = dynamic(() => import("@/components/run-session-overview").then((mod) => mod.RunSessionOverview), {
  loading: () => <Skeleton className="h-[320px]" />
});
const UnresolvedConflictCard = dynamic(() => import("@/components/unresolved-conflict-card").then((mod) => mod.UnresolvedConflictCard), {
  loading: () => <Skeleton className="h-28" />
});
const MarkdownViewer = dynamic(() => import("@/components/markdown-viewer").then((mod) => mod.MarkdownViewer), {
  loading: () => <Skeleton className="h-56" />
});

type TimelineEvent = DiscussionEvent & { payload: Record<string, unknown> };

function runTone(status?: string | null): "default" | "success" | "warn" | "danger" {
  if (status === "finished") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "paused") return "warn";
  return "default";
}

function eventTone(eventType: string): "default" | "success" | "warn" | "danger" {
  if (eventType === "message_completed" || eventType === "report_generated") return "success";
  if (eventType === "user_input") return "warn";
  if (eventType === "tool_failed" || eventType === "error") return "danger";
  if (eventType.startsWith("tool_")) return "warn";
  return "default";
}

function toggleKey(list: EventFilterKey[], key: EventFilterKey): EventFilterKey[] {
  const exists = list.includes(key);
  if (exists) {
    const next = list.filter((item) => item !== key);
    return next.length ? next : list;
  }
  return [...list, key];
}

function toggleExpanded(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function asObjectList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null) : [];
}

function isModeratorSummary(payload: Record<string, unknown>): boolean {
  return asRecord(payload.metadata).message_kind === "moderator_summary";
}

function isImportantUserInput(payload: Record<string, unknown>): boolean {
  return asRecord(payload.metadata).mark_important === true;
}

function StatCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-[22px] border border-[var(--line)] bg-[var(--panel)] px-3 py-3">
      <div className="text-[11px] text-[var(--muted)]">{label}</div>
      <div className="mt-1 text-lg font-semibold text-[var(--text)]">{value}</div>
      {hint ? <div className="mt-1 text-[11px] text-[var(--muted)]">{hint}</div> : null}
    </div>
  );
}

function ToolLogCard({ log, expanded, onToggle }: { log: ToolCallLog; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="rounded-[24px] border border-amber-500/20 bg-amber-500/8 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-amber-700 dark:text-amber-300">{log.tool_name} · 第 {log.round_no} 轮</div>
          <div className="text-xs text-[var(--muted)]">{formatDateTime(log.started_at)}</div>
        </div>
        <Badge tone={log.status === "completed" ? "success" : log.status === "failed" ? "danger" : "warn"}>{log.status}</Badge>
      </div>
      {"text" in log.tool_output_json ? <div className="whitespace-pre-wrap break-words text-sm text-[var(--text)]">{String(log.tool_output_json.text ?? "")}</div> : null}
      <JsonDetails
        expanded={expanded}
        onToggle={onToggle}
        payload={{
          call_id: log.call_id,
          input: log.tool_input_json,
          output: log.tool_output_json,
          started_at: log.started_at,
          ended_at: log.ended_at,
          status: log.status
        }}
      />
    </div>
  );
}

export default function RunDetailPage() {
  const { toast } = useToast();
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [wsState, setWsState] = useState("connecting");
  const [selectedFilters, setSelectedFilters] = useState<EventFilterKey[]>(["message", "status"]);
  const [expandedEventIds, setExpandedEventIds] = useState<string[]>([]);
  const [expandedToolLogIds, setExpandedToolLogIds] = useState<string[]>([]);
  const [controlMessage, setControlMessage] = useState("");
  const [markImportant, setMarkImportant] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [stickToBottom, setStickToBottom] = useState(true);
  const chatScrollerRef = useRef<HTMLDivElement | null>(null);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  const {
    run,
    setRun,
    session,
    setSession,
    agents,
    models,
    events,
    setEvents,
    toolLogs,
    setToolLogs,
    report,
    setReport,
    error,
    setError,
    loading
  } = useRunBundle(runId);

  useEffect(() => {
    if (!runId) return;
    let mounted = true;
    let socket: WebSocket | null = null;

    async function refreshRun() {
      const latest = await api.get<DiscussionRun>(`/runs/${runId}`);
      if (!mounted) return latest;
      setRun(latest);
      if (latest.session_id) {
        const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
        if (mounted) setSession(latestSession);
      }
      return latest;
    }

    async function refreshToolLogs() {
      const logs = await api.get<ToolCallLog[]>(`/runs/${runId}/tool-logs`);
      if (mounted) setToolLogs(logs);
    }

    async function refreshReport() {
      try {
        const latestReport = await api.get<FinalReport>(`/runs/${runId}/report`);
        if (mounted) setReport(latestReport);
      } catch {
        if (mounted) setReport(null);
      }
    }

    socket = new WebSocket(wsUrl(runId));
    socket.onopen = () => setWsState("connected");
    socket.onerror = () => setWsState("error");
    socket.onclose = () => setWsState("closed");
    socket.onmessage = async (message) => {
      const event: DiscussionEvent = JSON.parse(message.data);
      if (!mounted) return;
      setEvents((prev) => (prev.some((item) => item.id === event.id) ? prev : [...prev, event]));
      if (event.event_type === "run_status") await refreshRun();
      if (event.event_type === "report_generated") await refreshReport();
      if (event.event_type.includes("tool") || event.event_type === "run_status") await refreshToolLogs();
    };

    return () => {
      mounted = false;
      socket?.close();
    };
  }, [runId, setEvents, setReport, setRun, setSession, setToolLogs]);

  const timeline = useMemo<TimelineEvent[]>(() => [...events].sort((a, b) => a.seq - b.seq).map((event) => ({ ...event, payload: normalizePayload(event) })), [events]);
  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);
  const visibleTimeline = useMemo(() => timeline.filter((event) => isEventVisible(event.event_type, selectedFilters)), [selectedFilters, timeline]);
  const sortedToolLogs = useMemo(() => [...toolLogs].sort((a, b) => a.started_at.localeCompare(b.started_at)), [toolLogs]);
  const participantAgents = useMemo(
    () => (session?.agent_ids ?? []).map((agentId) => agents.find((agent) => agent.id === agentId)).filter((item): item is (typeof agents)[number] => Boolean(item)),
    [agents, session?.agent_ids]
  );

  const discussionMetrics = useMemo(() => {
    const userMessages = visibleTimeline.filter((event) => event.event_type === "user_input").length;
    const importantUserMessages = visibleTimeline.filter((event) => event.event_type === "user_input" && isImportantUserInput(event.payload)).length;
    const agentMessages = visibleTimeline.filter((event) => event.event_type === "message_completed" && !isModeratorSummary(event.payload)).length;
    const moderatorSummaries = visibleTimeline.filter((event) => event.event_type === "message_completed" && isModeratorSummary(event.payload)).length;
    const systemEvents = visibleTimeline.filter((event) => !["message_completed", "user_input"].includes(event.event_type)).length;

    return { userMessages, importantUserMessages, agentMessages, moderatorSummaries, systemEvents };
  }, [visibleTimeline]);

  const latestVisibleEvent = visibleTimeline.at(-1) ?? null;
  const latestStructuredState = useMemo(() => latestStructuredStatePreview(timeline), [timeline]);
  const pinnedPoints = useMemo(() => asStringList(asRecord(latestStructuredState).user_pinned_points), [latestStructuredState]);
  const unresolvedConflicts = useMemo(() => asStringList(asRecord(latestStructuredState).unresolved_conflicts), [latestStructuredState]);
  const unresolvedConflictDetails = useMemo(() => asObjectList(asRecord(latestStructuredState).unresolved_conflict_details), [latestStructuredState]);
  const patchMetrics = useMemo(() => asRecord(asRecord(latestStructuredState).patch_metrics), [latestStructuredState]);
  const overallAdoptionRate = patchMetrics.moderator_adoption_rate;
  const nextFocus = String(asRecord(latestStructuredState).next_focus ?? "");

  useEffect(() => {
    const node = chatScrollerRef.current;
    if (!node) return;

    const handleScroll = () => {
      const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
      setStickToBottom(distanceToBottom < 120);
    };

    handleScroll();
    node.addEventListener("scroll", handleScroll);
    return () => node.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    if (!stickToBottom) return;
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [stickToBottom, visibleTimeline.length]);

  async function refreshRunSnapshot() {
    const latest = await api.get<DiscussionRun>(`/runs/${runId}`);
    setRun(latest);
    if (latest.session_id) {
      const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
      setSession(latestSession);
    }
    return latest;
  }

  async function submitRunAction(type: "pause" | "resume" | "input" | "stop") {
    try {
      setActionBusy(type);
      if (type === "stop") {
        await api.post(`/runs/${runId}/stop`, { source: "frontend" });
        await refreshRunSnapshot();
        toast({ tone: "success", title: "运行已停止", description: "你可以稍后继续查看事件与报告。" });
        return;
      }

      const payload =
        type === "input"
          ? {
              message: controlMessage,
              source: "frontend",
              pause: run?.status === "running",
              mark_important: markImportant
            }
          : {
              message: controlMessage || undefined,
              source: "frontend",
              mark_important: markImportant
            };

      const endpoint = type === "pause" ? "pause" : type === "resume" ? "resume" : "user-input";
      const latest = await api.post<DiscussionRun>(`/runs/${runId}/${endpoint}`, payload);
      setRun(latest);
      if (latest.session_id) {
        const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
        setSession(latestSession);
      }
      if (controlMessage) setControlMessage("");
      setMarkImportant(false);
      toast({
        tone: "success",
        title: type === "pause" ? "运行已暂停" : type === "resume" ? "运行已恢复" : "补充信息已提交",
        description: type === "input" ? "消息已注入当前讨论流程。" : "运行状态已更新。"
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "运行控制失败";
      setError(message);
      toast({ tone: "danger", title: "运行控制失败", description: message });
    } finally {
      setActionBusy(null);
    }
  }

  async function handleMarkEventImportant(event: TimelineEvent) {
    const text = String(event.payload.text ?? "").trim();
    if (!text) return;
    try {
      setActionBusy(`pin:${event.id}`);
      const prefix =
        event.event_type === "user_input"
          ? "请将以下用户消息设为重点关注："
          : `请将第 ${event.round_no} 轮 ${String(event.payload.agent_name ?? "该智能体")} 的历史消息设为重点关注：`;
      const latest = await api.post<DiscussionRun>(`/runs/${runId}/user-input`, {
        message: `${prefix}\n${text}`,
        source: "frontend_pin_message",
        pause: false,
        mark_important: true
      });
      setRun(latest);
      if (latest.session_id) {
        const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
        setSession(latestSession);
      }
      toast({ tone: "success", title: "已设为重点关注", description: "这条内容会进入更长期的关注列表。" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "标记重点失败";
      setError(message);
      toast({ tone: "danger", title: "标记重点失败", description: message });
    } finally {
      setActionBusy(null);
    }
  }

  function scrollChatToBottom() {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  if (loading) {
    return (
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="grid gap-6">
          <Skeleton className="h-[280px]" />
          <Skeleton className="h-[980px]" />
        </div>
        <div className="grid gap-6">
          <Skeleton className="h-[280px]" />
          <Skeleton className="h-[320px]" />
          <Skeleton className="h-[320px]" />
        </div>
      </div>
    );
  }

  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="grid min-w-0 gap-6">
        <Card>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0 flex-1">
              <SectionTitle eyebrow="Live Run" title="运行详情" desc="实时观察当前讨论、状态变更、结构化结论与最终报告，和历史回放保持统一视觉体验。" />
              <div className="flex flex-wrap gap-2">
                <Badge>Run ID：{runId}</Badge>
                <Badge tone={runTone(run?.status)}>状态：{run?.status ?? "-"}</Badge>
                <Badge>轮次：{run?.current_round ?? 0}</Badge>
                <Badge tone={wsState === "connected" ? "success" : wsState === "error" ? "danger" : "warn"}>WebSocket：{wsState}</Badge>
                <Badge>开始时间：{formatDateTime(run?.started_at)}</Badge>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link href={`/runs/${runId}/replay`} className="btn-secondary inline-flex items-center rounded-2xl px-4 py-2.5 text-sm font-medium">
                进入回放
              </Link>
            </div>
          </div>

          <div className="mt-5">
            <RunSessionOverview session={session} participantAgents={participantAgents} agentDirectory={agentDirectory} />
          </div>
        </Card>

        {error ? <InlineAlert tone="danger" title="运行页有一项操作失败" description={error} /> : null}

        <Card className="overflow-hidden p-0">
          <div className="border-b border-[var(--line)] px-5 py-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <SectionTitle eyebrow="Timeline" title="讨论记录" desc="以聊天视图查看发言、主持人总结与系统事件，支持筛选和重点标记。" />
              <EventFilterPanel selected={selectedFilters} onToggle={(key) => setSelectedFilters((prev) => toggleKey(prev, key))} />
            </div>

            <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              <StatCard label="Agent 发言" value={discussionMetrics.agentMessages} />
              <StatCard label="主持人总结" value={discussionMetrics.moderatorSummaries} />
              <StatCard label="用户补充" value={discussionMetrics.userMessages} hint={discussionMetrics.importantUserMessages ? `重点 ${discussionMetrics.importantUserMessages} 条` : undefined} />
              <StatCard label="系统事件" value={discussionMetrics.systemEvents} hint={latestVisibleEvent ? `最新：${formatDateTime(latestVisibleEvent.created_at)}` : undefined} />
              <StatCard label="Moderator 采纳率" value={typeof overallAdoptionRate === "number" ? `${Math.round(overallAdoptionRate * 100)}%` : "-"} hint={typeof patchMetrics.moderator_patch_decisions === "number" ? `样本 ${patchMetrics.moderator_patch_decisions}` : undefined} />
            </div>
          </div>

          <div ref={chatScrollerRef} className="max-h-[calc(100vh-240px)] overflow-y-auto bg-[var(--panel)]">
            <div className="space-y-4 px-5 py-5 xl:px-6">
              {visibleTimeline.map((event, index) => {
                const payload = event.payload;
                const fallbackName = typeof payload.agent_name === "string" ? payload.agent_name : undefined;
                const agent = resolveAgentDisplay(agentDirectory, event.agent_id, fallbackName);
                const expanded = expandedEventIds.includes(event.id);

                if (event.event_type === "user_input") {
                  const important = isImportantUserInput(payload);
                  return (
                    <div key={event.id} className="fade-in-up flex justify-end" style={{ animationDelay: `${Math.min(index * 28, 220)}ms` }}>
                      <div className={`max-w-[85%] rounded-[24px] rounded-br-md border px-4 py-3 shadow-sm ${important ? "border-amber-400/30 bg-amber-500/12" : "border-sky-400/20 bg-sky-500/12"}`}>
                        <div className="mb-2 flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2 text-sm font-medium">
                            <span className={important ? "text-amber-600 dark:text-amber-300" : "text-[var(--brand-strong)]"}>{important ? "用户重点关注" : "用户补充"}</span>
                            {important ? <Badge tone="warn">Pinned</Badge> : null}
                          </div>
                          <div className="flex items-center gap-2">
                            {!important ? (
                              <button type="button" onClick={() => void handleMarkEventImportant(event)} disabled={Boolean(actionBusy)} className="text-xs text-amber-500 transition hover:text-amber-400 disabled:opacity-50">
                                {actionBusy === `pin:${event.id}` ? "标记中..." : "设为重点"}
                              </button>
                            ) : null}
                            <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                          </div>
                        </div>
                        <div className="whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{String(payload.text ?? "")}</div>
                        <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} />
                      </div>
                    </div>
                  );
                }

                if (event.event_type === "message_completed") {
                  if (isModeratorSummary(payload)) {
                    return (
                      <div key={event.id} className="fade-in-up flex justify-center" style={{ animationDelay: `${Math.min(index * 28, 220)}ms` }}>
                        <div className="w-full max-w-[92%] rounded-[28px] border border-amber-500/20 bg-amber-500/10 px-4 py-4 shadow-sm">
                          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                            <div className="flex min-w-0 items-center gap-3">
                              <AgentAvatar seed={agent.seed} name={agent.name} className="h-9 w-9" />
                              <div className="min-w-0">
                                <div className="truncate text-sm font-medium text-amber-700 dark:text-amber-300">{agent.label}</div>
                                <div className="text-xs text-[var(--muted)]">主持人总结 · 第 {event.round_no} 轮</div>
                              </div>
                            </div>
                            <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                          </div>
                          <div className="whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{String(payload.text ?? "")}</div>
                          <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} />
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div key={event.id} className="fade-in-up flex justify-start" style={{ animationDelay: `${Math.min(index * 28, 220)}ms` }}>
                      <div className="flex max-w-[88%] items-start gap-3">
                        <AgentAvatar seed={agent.seed} name={agent.name} className="mt-1 h-10 w-10" />
                        <div className="min-w-0 flex-1">
                          <div className="mb-2 flex flex-wrap items-center gap-3">
                            <div className="truncate text-sm font-medium text-[var(--brand-strong)]">{agent.label}</div>
                            <div className="text-xs text-[var(--muted)]">第 {event.round_no} 轮</div>
                            <button type="button" onClick={() => void handleMarkEventImportant(event)} disabled={Boolean(actionBusy)} className="text-xs text-amber-500 transition hover:text-amber-400 disabled:opacity-50">
                              {actionBusy === `pin:${event.id}` ? "标记中..." : "设为重点"}
                            </button>
                            <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                          </div>
                          <div className="rounded-[24px] rounded-tl-md border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 shadow-sm">
                            <div className="whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{String(payload.text ?? "")}</div>
                          </div>
                          <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} className="pl-1" />
                        </div>
                      </div>
                    </div>
                  );
                }

                return (
                  <div key={event.id} className="fade-in-up flex justify-center" style={{ animationDelay: `${Math.min(index * 28, 220)}ms` }}>
                    <div className="max-w-[92%] rounded-full border border-[var(--line)] bg-[var(--panel-2)] px-4 py-2 text-center text-xs text-[var(--muted)]">
                      <div className="flex flex-wrap items-center justify-center gap-2">
                        <Badge tone={eventTone(event.event_type)}>{eventTypeLabel(event.event_type)}</Badge>
                        <span>{summarizeEvent(event)}</span>
                        <span>{formatDateTime(event.created_at)}</span>
                      </div>
                      <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} />
                    </div>
                  </div>
                );
              })}

              {!visibleTimeline.length ? <EmptyState title="当前筛选条件下没有可展示内容" description="你可以切换事件类型筛选，或等待新的运行事件推送进来。" /> : null}
              <div ref={chatBottomRef} />
            </div>
          </div>

          <div className="flex flex-col gap-3 border-t border-[var(--line)] bg-[var(--panel-2)] px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-[var(--muted)]">{latestVisibleEvent ? `最新事件时间：${formatDateTime(latestVisibleEvent.created_at)}` : "暂无讨论事件"}</div>
            <div className="flex flex-wrap gap-2">
              {!stickToBottom && visibleTimeline.length ? (
                <SecondaryButton type="button" onClick={scrollChatToBottom} className="px-3 py-1.5 text-xs">
                  跳到最新消息
                </SecondaryButton>
              ) : null}
            </div>
          </div>
        </Card>
      </div>

      <div className="min-w-0 xl:sticky xl:top-8 xl:self-start">
        <div className="grid min-w-0 gap-6">
          <Card>
            <SectionTitle eyebrow="Controls" title="运行控制" desc="支持暂停、恢复、注入补充信息和停止运行。" />
            <Textarea value={controlMessage} onChange={(event) => setControlMessage(event.target.value)} placeholder="输入补充信息；运行中提交会自动暂停并注入，恢复后继续推进讨论。" className="min-h-28" />
            <div className="mt-4">
              <CheckboxRow checked={markImportant} onChange={setMarkImportant} label="标记为重点关注" description="这条输入会进入更长期的关注列表，便于后续检索与对齐。" />
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <SecondaryButton type="button" loading={actionBusy === "pause"} onClick={() => void submitRunAction("pause")} disabled={Boolean(actionBusy) || run?.status !== "running"}>
                暂停并注入
              </SecondaryButton>
              <PrimaryButton type="button" loading={actionBusy === "resume"} onClick={() => void submitRunAction("resume")} disabled={Boolean(actionBusy) || run?.status !== "paused"}>
                继续运行
              </PrimaryButton>
              <SecondaryButton type="button" loading={actionBusy === "input"} onClick={() => void submitRunAction("input")} disabled={Boolean(actionBusy) || !controlMessage.trim()}>
                {markImportant ? "提交重点信息" : "提交补充信息"}
              </SecondaryButton>
              <SecondaryButton type="button" loading={actionBusy === "stop"} onClick={() => void submitRunAction("stop")} disabled={Boolean(actionBusy) || ["finished", "failed", "stopped"].includes(run?.status ?? "")}>
                停止讨论
              </SecondaryButton>
            </div>
          </Card>

          <Card>
            <SectionTitle eyebrow="Structured State" title="当前焦点与冲突" desc="展示主持人最近一次结构化状态中的重点信息。" />
            <div className="space-y-4 text-sm">
              <div>
                <div className="mb-1 text-xs text-[var(--muted)]">下一步焦点</div>
                <div className="whitespace-pre-wrap break-words text-[var(--text)]">{nextFocus || "暂无"}</div>
              </div>

              <div>
                <div className="mb-2 flex items-center gap-2 text-xs text-[var(--muted)]">
                  <span>用户重点关注</span>
                  {pinnedPoints.length ? <Badge tone="warn">{pinnedPoints.length}</Badge> : null}
                </div>
                <div className="space-y-2">
                  {pinnedPoints.length ? pinnedPoints.map((item, index) => <div key={`${item}-${index}`} className="rounded-[22px] border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[var(--text)]">{item}</div>) : <EmptyState title="暂无重点关注" description="你可以在运行中提交重点信息，或把某条历史发言标记为重点。" />}
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center gap-2 text-xs text-[var(--muted)]">
                  <span>未解决冲突</span>
                  {unresolvedConflicts.length ? <Badge tone="danger">{unresolvedConflicts.length}</Badge> : null}
                </div>
                <div className="space-y-2">
                  {unresolvedConflictDetails.length ? (
                    unresolvedConflictDetails.map((item, index) => {
                      const summary = String(item.summary ?? unresolvedConflicts[index] ?? "未解决冲突");
                      return <UnresolvedConflictCard key={`${summary}-${index}`} detail={item} fallbackSummary={summary} />;
                    })
                  ) : unresolvedConflicts.length ? (
                    unresolvedConflicts.map((item, index) => <div key={`${item}-${index}`} className="rounded-[22px] border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[var(--text)]">{item}</div>)
                  ) : (
                    <EmptyState title="没有挂起冲突" description="当前结构化状态中没有 unresolved_conflict。" />
                  )}
                </div>
              </div>
            </div>
          </Card>

          <Card>
            <SectionTitle eyebrow="Tool Logs" title="工具调用日志" desc="聚焦查看工具执行结果，避免干扰主聊天区。" />
            <div className="max-h-[340px] space-y-3 overflow-y-auto pr-1">
              {sortedToolLogs.map((log) => (
                <ToolLogCard key={log.id} log={log} expanded={expandedToolLogIds.includes(log.id)} onToggle={() => setExpandedToolLogIds((prev) => toggleExpanded(prev, log.id))} />
              ))}
              {!sortedToolLogs.length ? <EmptyState title="暂无工具调用日志" description="当运行触发 Tool / MCP 调用后，这里会自动补充执行记录。" /> : null}
            </div>
          </Card>

          <Card>
            <SectionTitle eyebrow="Final Report" title="最终报告" desc="运行结束或生成报告后，这里会展示摘要与结构化结论。" />
            {report ? (
              <div className="space-y-4">
                <div className="rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
                  <div className="text-base font-semibold text-[var(--text)]">{report.title}</div>
                  <MarkdownViewer content={report.summary_markdown} className="mt-3" />
                </div>
                <details className="rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
                  <summary className="cursor-pointer text-sm font-medium text-[var(--brand-strong)]">查看结构化结论 JSON</summary>
                  <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(report.conclusion_json, null, 2)}</pre>
                </details>
              </div>
            ) : (
              <EmptyState title="报告尚未生成" description="运行结束后如果后端已产出报告，这里会自动出现 Markdown 摘要与结构化结论。" />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

