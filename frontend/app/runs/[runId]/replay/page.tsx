"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AgentAvatar, EventFilterPanel, JsonDetails } from "@/components/discussion-ui";
import { Badge, Card, EmptyState, InlineAlert, PrimaryButton, SecondaryButton, SectionTitle, Skeleton, useToast } from "@/components/ui";
import { api, ChatSession, DiscussionEvent, DiscussionRun, ToolCallLog } from "@/lib/api";
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

export default function RunReplayPage() {
  const { toast } = useToast();
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selectedFilters, setSelectedFilters] = useState<EventFilterKey[]>(["message", "status"]);
  const [expandedEventIds, setExpandedEventIds] = useState<string[]>([]);
  const [expandedToolLogIds, setExpandedToolLogIds] = useState<string[]>([]);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const currentEventRef = useRef<HTMLDivElement | null>(null);

  const { run, setRun, session, setSession, agents, models, events, toolLogs, report, error, setError, loading } = useRunBundle(runId);

  const timeline = useMemo<TimelineEvent[]>(() => [...events].sort((a, b) => a.seq - b.seq).map((event) => ({ ...event, payload: normalizePayload(event) })), [events]);
  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);
  const filteredTimeline = useMemo(() => timeline.filter((event) => isEventVisible(event.event_type, selectedFilters)), [selectedFilters, timeline]);
  const maxIndex = filteredTimeline.length ? filteredTimeline.length - 1 : 0;
  const currentEvent = filteredTimeline[cursor];
  const visibleTimeline = filteredTimeline.slice(0, filteredTimeline.length ? cursor + 1 : 0);
  const replayCutoffSeq = currentEvent?.seq ?? -1;
  const latestStructuredState = useMemo(() => latestStructuredStatePreview(replayCutoffSeq >= 0 ? timeline.filter((event) => event.seq <= replayCutoffSeq) : []), [replayCutoffSeq, timeline]);
  const nextFocus = String(asRecord(latestStructuredState).next_focus ?? "");
  const pinnedPoints = useMemo(() => asStringList(asRecord(latestStructuredState).user_pinned_points), [latestStructuredState]);
  const unresolvedConflicts = useMemo(() => asStringList(asRecord(latestStructuredState).unresolved_conflicts), [latestStructuredState]);
  const unresolvedConflictDetails = useMemo(() => asObjectList(asRecord(latestStructuredState).unresolved_conflict_details), [latestStructuredState]);

  const visibleToolLogs = currentEvent ? toolLogs.filter((log) => new Date(log.started_at).getTime() <= new Date(currentEvent.created_at).getTime()) : [];

  const participantAgents = useMemo(
    () => (session?.agent_ids ?? []).map((agentId) => agents.find((agent) => agent.id === agentId)).filter((item): item is (typeof agents)[number] => Boolean(item)),
    [agents, session?.agent_ids]
  );

  const replayMetrics = useMemo(() => {
    const messages = visibleTimeline.filter((event) => event.event_type === "message_completed" && !isModeratorSummary(event.payload)).length;
    const moderatorSummaries = visibleTimeline.filter((event) => event.event_type === "message_completed" && isModeratorSummary(event.payload)).length;
    const userMessages = visibleTimeline.filter((event) => event.event_type === "user_input").length;
    const systemEvents = visibleTimeline.filter((event) => !["message_completed", "user_input"].includes(event.event_type)).length;
    return { messages, moderatorSummaries, userMessages, systemEvents };
  }, [visibleTimeline]);

  const currentEventAgent = currentEvent && (Boolean(currentEvent.agent_id) || typeof currentEvent.payload.agent_name === "string") ? resolveAgentDisplay(agentDirectory, currentEvent.agent_id, typeof currentEvent.payload.agent_name === "string" ? currentEvent.payload.agent_name : undefined) : null;

  useEffect(() => {
    setCursor(0);
    setPlaying(false);
  }, [selectedFilters]);

  useEffect(() => {
    setCursor((prev) => Math.min(prev, maxIndex));
  }, [maxIndex]);

  useEffect(() => {
    if (!playing || maxIndex <= 0) return;
    if (cursor >= maxIndex) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setCursor((prev) => Math.min(prev + 1, maxIndex)), 760);
    return () => window.clearTimeout(timer);
  }, [playing, cursor, maxIndex]);

  useEffect(() => {
    currentEventRef.current?.scrollIntoView({ behavior: playing ? "smooth" : "auto", block: "center" });
  }, [cursor, playing]);

  function jump(step: number) {
    setCursor((value) => Math.max(0, Math.min(maxIndex, value + step)));
  }

  async function handleMarkEventImportant(event: TimelineEvent) {
    const text = String(event.payload.text ?? "").trim();
    if (!text) return;
    try {
      setActionBusy(`pin:${event.id}`);
      const prefix = event.event_type === "user_input" ? "请将以下用户消息设为重点关注：" : `请将第 ${event.round_no} 轮 ${String(event.payload.agent_name ?? "该智能体")} 的历史消息设为重点关注：`;
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

  if (loading) {
    return (
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-6">
          <Skeleton className="h-[280px]" />
          <Skeleton className="h-[980px]" />
        </div>
        <div className="grid gap-6">
          <Skeleton className="h-[280px]" />
          <Skeleton className="h-[280px]" />
          <Skeleton className="h-[420px]" />
        </div>
      </div>
    );
  }

  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="grid min-w-0 gap-6">
        <Card>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0 flex-1">
              <SectionTitle eyebrow="Replay" title="运行回放" desc="按事件序列重播多智能体协作过程，和实时运行页保持一致的层级、空状态与反馈节奏。" />
              <div className="flex flex-wrap gap-2">
                <Badge>Run ID：{runId}</Badge>
                <Badge tone={runTone(run?.status)}>状态：{run?.status ?? "-"}</Badge>
                <Badge>回放进度：{filteredTimeline.length ? cursor + 1 : 0}/{filteredTimeline.length}</Badge>
                <Badge>结束时间：{formatDateTime(run?.ended_at)}</Badge>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link href={`/runs/${runId}`} className="btn-secondary inline-flex items-center rounded-2xl px-4 py-2.5 text-sm font-medium">
                返回实时详情
              </Link>
            </div>
          </div>

          <div className="mt-5">
            <RunSessionOverview session={session} participantAgents={participantAgents} agentDirectory={agentDirectory} />
          </div>
        </Card>

        {error ? <InlineAlert tone="danger" title="回放页有一项操作失败" description={error} /> : null}

        <Card className="overflow-hidden p-0">
          <div className="border-b border-[var(--line)] px-5 py-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <SectionTitle eyebrow="Timeline Replay" title="回放记录" desc="按当前游标显示已发生的讨论内容，支持消息 / 系统事件联合过滤。" />
              <EventFilterPanel selected={selectedFilters} onToggle={(key) => setSelectedFilters((prev) => toggleKey(prev, key))} />
            </div>

            <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard label="Agent 发言" value={replayMetrics.messages} />
              <StatCard label="主持人总结" value={replayMetrics.moderatorSummaries} />
              <StatCard label="用户补充" value={replayMetrics.userMessages} />
              <StatCard label="系统事件" value={replayMetrics.systemEvents} hint={currentEvent ? `当前：${formatDateTime(currentEvent.created_at)}` : undefined} />
            </div>
          </div>

          <div className="max-h-[calc(100vh-240px)] overflow-y-auto bg-[var(--panel)]">
            <div className="space-y-4 px-5 py-5 xl:px-6">
              {visibleTimeline.map((event, index) => {
                const payload = event.payload;
                const fallbackName = typeof payload.agent_name === "string" ? payload.agent_name : undefined;
                const agent = resolveAgentDisplay(agentDirectory, event.agent_id, fallbackName);
                const expanded = expandedEventIds.includes(event.id);
                const isCurrent = currentEvent?.id === event.id;
                const currentClass = isCurrent ? "ring-2 ring-[var(--brand-strong)]/70 ring-offset-2 ring-offset-transparent" : "";

                if (event.event_type === "user_input") {
                  const important = isImportantUserInput(payload);
                  return (
                    <div key={event.id} ref={isCurrent ? currentEventRef : null} className="fade-in-up flex justify-end" style={{ animationDelay: `${Math.min(index * 26, 220)}ms` }}>
                      <div className={`max-w-[85%] rounded-[24px] rounded-br-md border px-4 py-3 shadow-sm ${important ? "border-amber-400/30 bg-amber-500/12" : "border-sky-400/20 bg-sky-500/12"} ${currentClass}`}>
                        <div className="mb-2 flex items-center justify-between gap-3">
                          <div className={`text-sm font-medium ${important ? "text-amber-600 dark:text-amber-300" : "text-[var(--brand-strong)]"}`}>{important ? "用户重点关注" : "用户补充"}</div>
                          <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                        </div>
                        <div className="whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{String(payload.text ?? "")}</div>
                        {!important ? (
                          <div className="mt-3">
                            <SecondaryButton type="button" onClick={() => void handleMarkEventImportant(event)} disabled={actionBusy === `pin:${event.id}`}>
                              {actionBusy === `pin:${event.id}` ? "提交中..." : "设为重点"}
                            </SecondaryButton>
                          </div>
                        ) : null}
                        <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} />
                      </div>
                    </div>
                  );
                }

                if (event.event_type === "message_completed") {
                  if (isModeratorSummary(payload)) {
                    return (
                      <div key={event.id} ref={isCurrent ? currentEventRef : null} className="fade-in-up flex justify-center" style={{ animationDelay: `${Math.min(index * 26, 220)}ms` }}>
                        <div className={`w-full max-w-[92%] rounded-[28px] border border-amber-500/20 bg-amber-500/10 px-4 py-4 shadow-sm ${currentClass}`}>
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
                    <div key={event.id} ref={isCurrent ? currentEventRef : null} className="fade-in-up flex justify-start" style={{ animationDelay: `${Math.min(index * 26, 220)}ms` }}>
                      <div className="flex max-w-[88%] items-start gap-3">
                        <AgentAvatar seed={agent.seed} name={agent.name} className="mt-1 h-10 w-10" />
                        <div className="min-w-0 flex-1">
                          <div className="mb-2 flex flex-wrap items-center gap-3">
                            <div className="truncate text-sm font-medium text-[var(--brand-strong)]">{agent.label}</div>
                            <div className="text-xs text-[var(--muted)]">第 {event.round_no} 轮</div>
                            <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                          </div>
                          <div className={`rounded-[24px] rounded-tl-md border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 shadow-sm ${currentClass}`}>
                            <div className="whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{String(payload.text ?? "")}</div>
                          </div>
                          <div className="mt-3 pl-1">
                            <SecondaryButton type="button" onClick={() => void handleMarkEventImportant(event)} disabled={actionBusy === `pin:${event.id}`}>
                              {actionBusy === `pin:${event.id}` ? "提交中..." : "设为重点"}
                            </SecondaryButton>
                          </div>
                          <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} className="pl-1" />
                        </div>
                      </div>
                    </div>
                  );
                }

                return (
                  <div key={event.id} ref={isCurrent ? currentEventRef : null} className="fade-in-up flex justify-center" style={{ animationDelay: `${Math.min(index * 26, 220)}ms` }}>
                    <div className={`max-w-[92%] rounded-full border border-[var(--line)] bg-[var(--panel-2)] px-4 py-2 text-center text-xs text-[var(--muted)] ${currentClass}`}>
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

              {!visibleTimeline.length ? <EmptyState title="当前筛选条件下没有可回放内容" description="你可以切换筛选器，或者移动到其他运行记录进行回放。" /> : null}
            </div>
          </div>
        </Card>
      </div>

      <div className="min-w-0 xl:sticky xl:top-8 xl:self-start">
        <div className="grid min-w-0 gap-6">
          <Card>
            <SectionTitle eyebrow="Playback" title="回放控制" desc="使用滑杆、步进和自动播放快速定位讨论过程。" />
            {filteredTimeline.length ? (
              <>
                <input type="range" min={0} max={maxIndex} value={cursor} onChange={(event) => setCursor(Number(event.target.value))} className="w-full accent-[var(--brand-strong)]" />
                <div className="mt-4 flex flex-wrap gap-3">
                  <PrimaryButton type="button" onClick={() => jump(-1)} disabled={cursor <= 0}>
                    上一步
                  </PrimaryButton>
                  <PrimaryButton type="button" onClick={() => jump(1)} disabled={cursor >= maxIndex}>
                    下一步
                  </PrimaryButton>
                  <SecondaryButton type="button" onClick={() => setPlaying((value) => !value)} disabled={maxIndex <= 0}>
                    {playing ? "暂停" : "自动播放"}
                  </SecondaryButton>
                  <SecondaryButton type="button" onClick={() => setCursor(0)} disabled={cursor === 0}>
                    回到开头
                  </SecondaryButton>
                  <SecondaryButton type="button" onClick={() => setCursor(maxIndex)} disabled={cursor >= maxIndex}>
                    跳到结尾
                  </SecondaryButton>
                </div>
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  <StatCard label="当前进度" value={`${filteredTimeline.length ? cursor + 1 : 0}/${filteredTimeline.length}`} />
                  <StatCard label="播放状态" value={playing ? "播放中" : "暂停中"} />
                </div>
              </>
            ) : (
              <EmptyState title="暂无可回放事件" description="当前筛选条件下没有匹配事件。" />
            )}
          </Card>

          <Card>
            <SectionTitle eyebrow="Current Event" title="当前事件" desc="显示游标所在事件的核心信息与结构化载荷。" />
            {currentEvent ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={eventTone(currentEvent.event_type)}>{eventTypeLabel(currentEvent.event_type)}</Badge>
                  <Badge>第 {currentEvent.round_no} 轮</Badge>
                  {currentEvent.tool_name ? <Badge tone="warn">{currentEvent.tool_name}</Badge> : null}
                </div>

                {currentEventAgent ? (
                  <div className="flex items-center gap-3">
                    <AgentAvatar seed={currentEventAgent.seed} name={currentEventAgent.name} className="h-10 w-10" />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-[var(--text)]">{currentEventAgent.label}</div>
                      <div className="text-xs text-[var(--muted)]">{formatDateTime(currentEvent.created_at)}</div>
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-[var(--muted)]">{formatDateTime(currentEvent.created_at)}</div>
                )}

                <div className="rounded-[22px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm leading-7 text-[var(--text)]">{String(currentEvent.payload.text ?? summarizeEvent(currentEvent))}</div>
                <JsonDetails expanded={expandedEventIds.includes(currentEvent.id)} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, currentEvent.id))} payload={currentEvent.payload} />
              </div>
            ) : (
              <EmptyState title="暂无当前事件" description="开始拖动时间轴或切换筛选条件后，这里会展示对应事件。" />
            )}
          </Card>

          <Card>
            <SectionTitle eyebrow="Tool Logs" title="累计工具日志" desc="按当前回放游标截断，便于还原当时上下文。" />
            <div className="max-h-[300px] space-y-3 overflow-y-auto pr-1">
              {visibleToolLogs.map((log) => <ToolLogCard key={log.id} log={log} expanded={expandedToolLogIds.includes(log.id)} onToggle={() => setExpandedToolLogIds((prev) => toggleExpanded(prev, log.id))} />)}
              {!visibleToolLogs.length ? <EmptyState title="当前阶段还没有工具调用" description="继续向后播放，若此轮触发了 Tool / MCP 调用，这里会自动出现。" /> : null}
            </div>
          </Card>

          <Card>
            <SectionTitle eyebrow="Replay Summary" title="回放摘要" desc="帮助快速理解当前回放进度，并在结尾查看最终报告。" />
            <div className="grid gap-2 sm:grid-cols-2">
              <StatCard label="累计事件" value={visibleTimeline.length} />
              <StatCard label="累计工具日志" value={visibleToolLogs.length} />
              <StatCard label="当前轮次" value={currentEvent?.round_no ?? "-"} />
              <StatCard label="结束时间" value={formatDateTime(run?.ended_at)} />
            </div>

            <div className="mt-4 space-y-4">
              <div className="rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
                <div className="text-sm font-semibold text-[var(--text)]">当前状态快照</div>
                <div className="mt-3 space-y-4 text-sm">
                  <div>
                    <div className="text-xs text-[var(--muted)]">下一步焦点</div>
                    <div className="mt-1 text-[var(--text)]">{nextFocus || "暂无"}</div>
                  </div>

                  <div>
                    <div className="text-xs text-[var(--muted)]">重点关注</div>
                    <div className="mt-2 space-y-2">
                      {pinnedPoints.length ? pinnedPoints.map((item, index) => <div key={`${item}-${index}`} className="rounded-[22px] border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[var(--text)]">{item}</div>) : <div className="text-[var(--muted)]">暂无</div>}
                    </div>
                  </div>

                  <div>
                    <div className="text-xs text-[var(--muted)]">未解决冲突</div>
                    <div className="mt-2 space-y-2">
                      {unresolvedConflictDetails.length ? (
                        unresolvedConflictDetails.map((item, index) => {
                          const summary = String(item.summary ?? unresolvedConflicts[index] ?? "未解决冲突");
                          return <UnresolvedConflictCard key={`${summary}-${index}`} detail={item} fallbackSummary={summary} />;
                        })
                      ) : unresolvedConflicts.length ? (
                        unresolvedConflicts.map((item, index) => <div key={`${item}-${index}`} className="rounded-[22px] border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[var(--text)]">{item}</div>)
                      ) : (
                        <div className="text-[var(--muted)]">暂无</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {report && cursor >= maxIndex && filteredTimeline.length > 0 ? (
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
                <EmptyState title="最终报告将在回放结束时展示" description="当你播放到结尾，且该 Run 已生成报告时，这里会自动显示 Markdown 摘要。" />
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
