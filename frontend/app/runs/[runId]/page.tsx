"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AgentAvatar, EventFilterPanel, JsonDetails } from "@/components/discussion-ui";
import { RunParticipantsPanel } from "@/components/run-participants-panel";
import { RunSessionOverview } from "@/components/run-session-overview";
import { Badge, Card, PrimaryButton, SectionTitle, SecondaryButton, Textarea } from "@/components/ui";
import { AgentConfig, api, ChatSession, DiscussionEvent, DiscussionRun, FinalReport, ToolCallLog, wsUrl } from "@/lib/api";
import { EventFilterKey, buildAgentDirectory, eventTypeLabel, isEventVisible, resolveAgentDisplay, summarizeEvent } from "@/lib/discussion";
import { formatDateTime, normalizePayload, useRunBundle } from "@/lib/run-bundle";

type TimelineEvent = DiscussionEvent & { payload: Record<string, unknown> };

function eventTone(eventType: string): "default" | "success" | "warn" | "danger" {
  if (eventType === "message_completed" || eventType === "report_generated") return "success";
  if (eventType === "user_input") return "warn";
  if (eventType === "tool_failed" || eventType === "error") return "danger";
  if (eventType.includes("tool")) return "warn";
  return "default";
}

function runTone(status?: string | null): "default" | "success" | "warn" | "danger" {
  if (status === "finished") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "paused") return "warn";
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

export default function RunDetailPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [wsState, setWsState] = useState("connecting");
  const [selectedFilters, setSelectedFilters] = useState<EventFilterKey[]>(["message"]);
  const [expandedEventIds, setExpandedEventIds] = useState<string[]>([]);
  const [expandedToolLogIds, setExpandedToolLogIds] = useState<string[]>([]);
  const [controlMessage, setControlMessage] = useState("");
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const { run, setRun, session, setSession, agents, models, events, setEvents, report, setReport, toolLogs, setToolLogs, error, setError } = useRunBundle(runId);

  useEffect(() => {
    if (!runId) return;
    let mounted = true;
    let socket: WebSocket | null = null;

    /**
     * 当 WebSocket 收到状态类事件时，再补拉一次 run / session 快照，
     * 确保页面顶部状态区与后端最终状态保持一致。
     */
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
        // 报告未生成是正常情况，这里不打断实时页。
      }
    }

    // 详情页通过 WebSocket 实时订阅新的讨论事件。
    socket = new WebSocket(wsUrl(runId));
    socket.onopen = () => setWsState("connected");
    socket.onerror = () => setWsState("error");
    socket.onclose = () => setWsState("closed");
    socket.onmessage = async (message) => {
      const event: DiscussionEvent = JSON.parse(message.data);
      if (!mounted) return;

      // 去重追加，避免刷新或重连后重复插入同一事件。
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

  const timeline = useMemo<TimelineEvent[]>(
    () =>
      [...events].sort((a, b) => a.seq - b.seq).map((event) => ({
        ...event,
        payload: normalizePayload(event)
      })),
    [events]
  );

  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);

  // 详情页默认只看发言，其他类型事件通过右上角筛选面板逐步打开。
  const visibleTimeline = useMemo(
    () => timeline.filter((event) => isEventVisible(event.event_type, selectedFilters)),
    [selectedFilters, timeline]
  );

  const sortedToolLogs = useMemo(
    () => [...toolLogs].sort((a, b) => a.started_at.localeCompare(b.started_at)),
    [toolLogs]
  );

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

  async function refreshRunSnapshot() {
    const latest = await api.get<DiscussionRun>(`/runs/${runId}`);
    setRun(latest);
    if (latest.session_id) {
      const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
      setSession(latestSession);
    }
    return latest;
  }

  async function handlePause() {
    try {
      setActionBusy("pause");
      const latest = await api.post<DiscussionRun>(`/runs/${runId}/pause`, {
        message: controlMessage || undefined,
        source: "frontend"
      });
      setRun(latest);
      if (latest.session_id) {
        const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
        setSession(latestSession);
      }
      if (controlMessage) setControlMessage("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function handleResume() {
    try {
      setActionBusy("resume");
      const latest = await api.post<DiscussionRun>(`/runs/${runId}/resume`, {
        message: controlMessage || undefined,
        source: "frontend"
      });
      setRun(latest);
      if (latest.session_id) {
        const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
        setSession(latestSession);
      }
      if (controlMessage) setControlMessage("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  }

  /**
   * 用户补充信息既可以作为纯注入消息，也可以在运行中触发安全暂停。
   */
  async function handleInjectInput() {
    if (!controlMessage.trim()) return;
    try {
      setActionBusy("input");
      const latest = await api.post<DiscussionRun>(`/runs/${runId}/user-input`, {
        message: controlMessage,
        source: "frontend",
        pause: run?.status === "running"
      });
      setRun(latest);
      if (latest.session_id) {
        const latestSession = await api.get<ChatSession>(`/chat-sessions/${latest.session_id}`);
        setSession(latestSession);
      }
      setControlMessage("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function handleStop() {
    try {
      setActionBusy("stop");
      await api.post(`/runs/${runId}/stop`, { source: "frontend" });
      await refreshRunSnapshot();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  }

  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
      <div className="grid min-w-0 gap-6">
        <Card>
          <SectionTitle title="运行状态" desc="通过 WebSocket 持续接收讨论过程。" />
          <div className="flex flex-wrap gap-3">
            <Badge>Run ID: {runId}</Badge>
            <Badge tone={runTone(run?.status)}>状态：{run?.status ?? "loading"}</Badge>
            <Badge>轮次：{run?.current_round ?? 0}</Badge>
            <Badge tone={wsState === "connected" ? "success" : wsState === "error" ? "danger" : "warn"}>WebSocket：{wsState}</Badge>
            <Badge>开始时间：{formatDateTime(run?.started_at)}</Badge>
          </div>

          <div className="mt-4 space-y-3 rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
            <div className="text-sm font-medium text-[var(--text)]">运行控制</div>
            <Textarea
              value={controlMessage}
              onChange={(event) => setControlMessage(event.target.value)}
              placeholder="可填写补充信息；暂停时会注入给所有智能体，恢复时也可携带补充说明。"
              className="min-h-28"
            />
            <div className="flex flex-wrap gap-3">
              <SecondaryButton onClick={handlePause} disabled={actionBusy !== null || run?.status !== "running"}>
                {actionBusy === "pause" ? "暂停中..." : "暂停并注入"}
              </SecondaryButton>
              <PrimaryButton onClick={handleResume} disabled={actionBusy !== null || run?.status !== "paused"}>
                {actionBusy === "resume" ? "继续中..." : "继续运行"}
              </PrimaryButton>
              <SecondaryButton onClick={handleInjectInput} disabled={actionBusy !== null || !controlMessage.trim()}>
                {actionBusy === "input" ? "提交中..." : "提交补充信息"}
              </SecondaryButton>
              <SecondaryButton onClick={handleStop} disabled={actionBusy !== null || ["finished", "failed", "stopped"].includes(run?.status ?? "")}>
                {actionBusy === "stop" ? "停止中..." : "停止讨论"}
              </SecondaryButton>
            </div>
            <p className="text-xs text-[var(--muted)]">当前支持软中断：暂停会在安全点打断当前智能体，并把补充信息广播给所有参与智能体；继续后按原顺序恢复。</p>
          </div>

          <div className="mt-4">
            <RunSessionOverview session={session} participants={participants} />
          </div>

          <div className="mt-4">
            <RunParticipantsPanel participantAgents={participantAgents} agentDirectory={agentDirectory} />
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            <Link href={`/runs/${runId}/replay`} className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] transition hover:border-sky-400">
              进入讨论回放
            </Link>
          </div>
          {error ? <p className="mt-3 text-sm text-rose-500">{error}</p> : null}
        </Card>

        <Card>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <SectionTitle title="讨论时间线" desc="支持按发言 / 工具 / 状态 / 报告过滤，并可展开 JSON 详情。" />
            <EventFilterPanel selected={selectedFilters} onToggle={(key) => setSelectedFilters((prev) => toggleKey(prev, key))} />
          </div>

          <div className="space-y-3">
            {visibleTimeline.map((event) => {
              const payload = event.payload;
              const fallbackName = typeof payload.agent_name === "string" ? payload.agent_name : undefined;
              const agent = resolveAgentDisplay(agentDirectory, event.agent_id, fallbackName);
              const expanded = expandedEventIds.includes(event.id);

              if (event.event_type === "message_completed") {
                return (
                  <div key={event.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
                    <div className="flex items-start gap-3">
                      <AgentAvatar seed={agent.seed} name={agent.name} className="h-10 w-10" />
                      <div className="min-w-0 flex-1">
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-sky-500">{agent.label}</div>
                            <div className="text-xs text-[var(--muted)]">第 {event.round_no} 轮</div>
                          </div>
                          <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                        </div>
                        <div className="whitespace-pre-wrap break-words text-sm text-[var(--text)]">{String(payload.text ?? "")}</div>
                        <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} />
                      </div>
                    </div>
                  </div>
                );
              }

              return (
                <div key={event.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <Badge tone={eventTone(event.event_type)}>{eventTypeLabel(event.event_type)}</Badge>
                      {event.tool_name ? <Badge tone="warn">{event.tool_name}</Badge> : null}
                      {event.agent_id ? <span className="truncate text-sm text-[var(--text)]">{agent.label}</span> : null}
                    </div>
                    <div className="text-xs text-[var(--muted)]">{formatDateTime(event.created_at)}</div>
                  </div>
                  <div className="break-words text-sm text-[var(--text)]">{summarizeEvent(event)}</div>
                  <JsonDetails expanded={expanded} onToggle={() => setExpandedEventIds((prev) => toggleExpanded(prev, event.id))} payload={payload} />
                </div>
              );
            })}
            {!visibleTimeline.length ? <p className="text-sm text-[var(--muted)]">当前筛选条件下暂无事件。</p> : null}
          </div>
        </Card>
      </div>

      <div className="grid min-w-0 gap-6">
        <Card>
          <SectionTitle title="工具调用日志" desc="展示工具输入、输出和执行状态。" />
          <div className="space-y-3">
            {sortedToolLogs.map((log) => {
              const agent = resolveAgentDisplay(agentDirectory, log.agent_id);
              const expanded = expandedToolLogIds.includes(log.id);

              return (
                <div key={log.id} className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-3">
                      <AgentAvatar seed={agent.seed} name={agent.name} className="h-8 w-8" />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-amber-600 dark:text-amber-300">{log.tool_name} · 第 {log.round_no} 轮</div>
                        <div className="truncate text-xs text-[var(--muted)]">{agent.label}</div>
                      </div>
                    </div>
                    <Badge tone={log.status === "completed" ? "success" : "warn"}>{log.status}</Badge>
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
            {!sortedToolLogs.length ? <p className="text-sm text-[var(--muted)]">暂无工具调用日志。</p> : null}
          </div>
        </Card>

        <Card>
          <SectionTitle title="最终结论报告" desc="基于讨论记录自动汇总生成，无需额外 Reporter Agent。" />
          {report ? (
            <div className="space-y-3">
              <h3 className="break-words text-lg font-medium text-[var(--text)]">{report.title}</h3>
              <article className="markdown-body rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.summary_markdown}</ReactMarkdown>
              </article>
              <details className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
                <summary className="cursor-pointer text-sm text-sky-500">查看结构化结论 JSON</summary>
                <pre className="mt-3 overflow-x-auto rounded-2xl bg-[var(--panel)] p-4 text-xs text-[var(--muted)]">{JSON.stringify(report.conclusion_json, null, 2)}</pre>
              </details>
            </div>
          ) : (
            <p className="text-sm text-[var(--muted)]">报告尚未生成。</p>
          )}
        </Card>
      </div>
    </div>
  );
}
