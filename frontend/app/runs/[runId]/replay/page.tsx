"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AgentAvatar, EventFilterPanel, JsonDetails } from "@/components/discussion-ui";
import { RunParticipantsPanel } from "@/components/run-participants-panel";
import { RunSessionOverview } from "@/components/run-session-overview";
import { Badge, Card, PrimaryButton, SecondaryButton, SectionTitle } from "@/components/ui";
import { AgentConfig, DiscussionEvent } from "@/lib/api";
import { EventFilterKey, buildAgentDirectory, eventTypeLabel, isEventVisible, resolveAgentDisplay, summarizeEvent } from "@/lib/discussion";
import { formatDateTime, normalizePayload, useRunBundle } from "@/lib/run-bundle";

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
  if (eventType.includes("tool")) return "warn";
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

export default function RunReplayPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selectedFilters, setSelectedFilters] = useState<EventFilterKey[]>(["message"]);
  const [expandedEventIds, setExpandedEventIds] = useState<string[]>([]);
  const [expandedToolLogIds, setExpandedToolLogIds] = useState<string[]>([]);
  const { run, session, agents, models, events, toolLogs, report, error } = useRunBundle(runId);

  const timeline = useMemo<TimelineEvent[]>(
    () =>
      [...events].sort((a, b) => a.seq - b.seq).map((event) => ({
        ...event,
        payload: normalizePayload(event)
      })),
    [events]
  );

  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);

  // 回放页允许按事件类型重新裁剪时间线，cursor 会跟随重置。
  const filteredTimeline = useMemo(
    () => timeline.filter((event) => isEventVisible(event.event_type, selectedFilters)),
    [selectedFilters, timeline]
  );

  const maxIndex = filteredTimeline.length ? filteredTimeline.length - 1 : 0;
  const currentEvent = filteredTimeline[cursor];
  const visibleEvents = filteredTimeline.slice(0, filteredTimeline.length ? cursor + 1 : 0);
  const visibleMessages = visibleEvents.filter((event) => ["message_completed", "user_input"].includes(event.event_type));

  /**
   * 工具日志不是按 seq 存储，因此回放时通过 started_at 与当前事件时间做截断。
   */
  const visibleToolLogs = currentEvent
    ? toolLogs.filter((log) => new Date(log.started_at).getTime() <= new Date(currentEvent.created_at).getTime())
    : [];

  const participants = useMemo(
    () =>
      (session?.agent_ids ?? [])
        .map((agentId) => agentDirectory[agentId])
        .filter((item): item is NonNullable<typeof item> => Boolean(item)),
    [agentDirectory, session?.agent_ids]
  );
  const participantAgents = useMemo(
    () =>
      (session?.agent_ids ?? [])
        .map((agentId) => agents.find((agent) => agent.id === agentId))
        .filter((item): item is AgentConfig => Boolean(item)),
    [agents, session?.agent_ids]
  );

  useEffect(() => {
    setCursor(0);
    setPlaying(false);
  }, [selectedFilters]);

  useEffect(() => {
    setCursor((prev) => Math.min(prev, maxIndex));
  }, [maxIndex]);

  /**
   * 自动播放本质上是一个固定间隔推进 cursor 的定时器。
   * 到达末尾后会自动停下，防止空转。
   */
  useEffect(() => {
    if (!playing || maxIndex <= 0) return;
    if (cursor >= maxIndex) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setCursor((prev) => Math.min(prev + 1, maxIndex)), 900);
    return () => window.clearTimeout(timer);
  }, [playing, cursor, maxIndex]);

  const currentEventHasAgent = Boolean(currentEvent?.agent_id) || typeof currentEvent?.payload.agent_name === "string";
  const currentEventAgent =
    currentEvent && currentEventHasAgent
      ? resolveAgentDisplay(
          agentDirectory,
          currentEvent.agent_id,
          typeof currentEvent.payload.agent_name === "string" ? currentEvent.payload.agent_name : undefined
        )
      : null;

  return (
    <div className="grid gap-6">
      <Card>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <SectionTitle title="讨论回放" desc="按事件序列逐步回看多 Agent 讨论过程。" />
            <div className="flex flex-wrap items-center gap-3">
              <Badge>Run ID: {runId}</Badge>
              <Badge tone={runTone(run?.status)}>状态：{run?.status ?? "-"}</Badge>
              <Badge>进度：{filteredTimeline.length ? cursor + 1 : 0}/{filteredTimeline.length}</Badge>
              <Link href={`/runs/${runId}`} className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] transition hover:border-sky-400">
                返回实时页
              </Link>
            </div>
          </div>
          <EventFilterPanel selected={selectedFilters} onToggle={(key) => setSelectedFilters((prev) => toggleKey(prev, key))} />
        </div>

        <div className="mt-4">
          <RunSessionOverview session={session} participants={participants} />
        </div>

        <div className="mt-4">
          <RunParticipantsPanel participantAgents={participantAgents} agentDirectory={agentDirectory} />
        </div>

        {filteredTimeline.length ? (
          <div className="mt-4 space-y-4">
            <input type="range" min={0} max={maxIndex} value={cursor} onChange={(e) => setCursor(Number(e.target.value))} className="w-full" />
            <div className="flex flex-wrap gap-3">
              <PrimaryButton type="button" onClick={() => setCursor((value) => Math.max(0, value - 1))}>
                上一步
              </PrimaryButton>
              <PrimaryButton type="button" onClick={() => setCursor((value) => Math.min(maxIndex, value + 1))}>
                下一步
              </PrimaryButton>
              <SecondaryButton type="button" onClick={() => setPlaying((value) => !value)}>
                {playing ? "暂停" : "自动播放"}
              </SecondaryButton>
              <SecondaryButton type="button" onClick={() => setCursor(0)}>
                回到开头
              </SecondaryButton>
            </div>
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--muted)]">当前筛选条件下暂无可回放事件。</p>
        )}
        {error ? <p className="mt-3 text-sm text-rose-500">{error}</p> : null}
      </Card>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <Card>
          <SectionTitle title="当前事件" desc="展示当前回放位置对应的事件详情。" />
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
                <div className="text-sm text-[var(--muted)]">{formatDateTime(currentEvent.created_at)}</div>
              )}
              <div className="break-words text-sm text-[var(--text)]">{summarizeEvent(currentEvent)}</div>
              <JsonDetails expanded={expandedEventIds.includes(currentEvent.id)} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, currentEvent.id))} payload={currentEvent.payload} />
            </div>
          ) : (
            <p className="text-sm text-[var(--muted)]">暂无事件。</p>
          )}
        </Card>

        <Card>
          <SectionTitle title="累计消息流" desc="显示当前回放位置之前已经出现的 Agent 发言。" />
          <div className="space-y-3">
            {visibleMessages.map((event) => {
              const fallbackName = typeof event.payload.agent_name === "string" ? event.payload.agent_name : undefined;
              const agent = resolveAgentDisplay(agentDirectory, event.agent_id, fallbackName);
              const isUserInput = event.event_type === "user_input";
              return (
                <div key={event.id} className={`rounded-2xl border p-4 ${isUserInput ? "border-amber-500/30 bg-amber-500/5" : "border-[var(--line)] bg-[var(--panel-2)]"}`}>
                  <div className="flex items-start gap-3">
                    <AgentAvatar seed={agent.seed} name={agent.name} className="h-10 w-10" />
                    <div className="min-w-0 flex-1">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className={`truncate text-sm font-medium ${isUserInput ? "text-amber-500" : "text-sky-500"}`}>{isUserInput ? "用户补充" : agent.label}</div>
                          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                            <span>第 {event.round_no} 轮</span>
                            <Badge tone={eventTone(event.event_type)}>{eventTypeLabel(event.event_type)}</Badge>
                          </div>
                        </div>
                        <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                      </div>
                      <div className="whitespace-pre-wrap break-words text-sm text-[var(--text)]">{String(event.payload.text ?? summarizeEvent(event))}</div>
                      <JsonDetails expanded={expandedEventIds.includes(event.id)} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={event.payload} />
                    </div>
                  </div>
                </div>
              );
            })}
            {!visibleMessages.length ? <p className="text-sm text-[var(--muted)]">当前阶段还没有消息或用户补充信息。</p> : null}
          </div>
        </Card>
      </div>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Card>
          <SectionTitle title="累计工具日志" desc="按当前事件时间截断显示。" />
          <div className="space-y-3">
            {visibleToolLogs.map((log) => {
              const agent = resolveAgentDisplay(agentDirectory, log.agent_id);
              const expanded = expandedToolLogIds.includes(log.id);

              return (
                <div key={log.id} className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-3">
                      <AgentAvatar seed={agent.seed} name={agent.name} className="h-8 w-8" />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-amber-600 dark:text-amber-300">{log.tool_name} · 第 {log.round_no} 轮</div>
                        <div className="truncate text-xs text-[var(--muted)]">{agent.label}</div>
                      </div>
                    </div>
                    <Badge tone={log.status === "completed" ? "success" : log.status === "failed" ? "danger" : "warn"}>{log.status}</Badge>
                  </div>
                  {"text" in log.tool_output_json ? <div className="whitespace-pre-wrap break-words text-sm text-[var(--text)]">{String(log.tool_output_json.text ?? "")}</div> : null}
                  <JsonDetails
                    expanded={expanded}
                    onToggle={() => setExpandedToolLogIds((prev) => toggleExpanded(prev, log.id))}
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
            })}
            {!visibleToolLogs.length ? <p className="text-sm text-[var(--muted)]">当前阶段还没有工具调用。</p> : null}
          </div>
        </Card>

        <Card>
          <SectionTitle title="回放摘要" desc="帮助快速理解当前回放进度。" />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] p-3">
              <div className="text-xs text-[var(--muted)]">累计事件</div>
              <div className="mt-1 text-2xl font-semibold text-[var(--text)]">{visibleEvents.length}</div>
            </div>
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] p-3">
              <div className="text-xs text-[var(--muted)]">累计消息</div>
              <div className="mt-1 text-2xl font-semibold text-[var(--text)]">{visibleMessages.length}</div>
            </div>
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] p-3">
              <div className="text-xs text-[var(--muted)]">累计工具日志</div>
              <div className="mt-1 text-2xl font-semibold text-[var(--text)]">{visibleToolLogs.length}</div>
            </div>
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] p-3">
              <div className="text-xs text-[var(--muted)]">结束时间</div>
              <div className="mt-1 text-sm font-semibold text-[var(--text)]">{formatDateTime(run?.ended_at)}</div>
            </div>
          </div>
          {report && cursor >= maxIndex && filteredTimeline.length > 0 ? (
            <details className="mt-4 rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
              <summary className="cursor-pointer font-medium text-[var(--text)]">最终报告已生成：{report.title}</summary>
              <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(report.conclusion_json, null, 2)}</pre>
            </details>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
