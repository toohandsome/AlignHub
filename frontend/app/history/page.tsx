"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AgentAvatar, AgentChip } from "@/components/discussion-ui";
import { Badge, Card, EmptyState, InlineAlert, PrimaryButton, SecondaryButton, SectionTitle, Skeleton, useToast } from "@/components/ui";
import { AgentConfig, api, ChatSession, DiscussionRun, ModelConfig } from "@/lib/api";
import { buildAgentDirectory } from "@/lib/discussion";
import { formatDateTime } from "@/lib/run-bundle";

function hasExplicitModerator(agentIds: string[], agents: AgentConfig[]) {
  return agentIds.some((agentId) => agents.find((agent) => agent.id === agentId)?.is_moderator);
}

function runTone(status: string): "default" | "success" | "warn" | "danger" {
  if (status === "finished") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "paused") return "warn";
  return "default";
}

const STATUS_FILTERS = ["all", "finished", "running", "paused", "failed", "stopped", "draft"] as const;

export default function HistoryPage() {
  const { toast } = useToast();
  const [runs, setRuns] = useState<DiscussionRun[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyRunId, setBusyRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [lastRunId, setLastRunId] = useState("");

  async function loadAll(mode: "initial" | "refresh" = "refresh") {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);

    try {
      const [runData, sessionData, agentData, modelData] = await Promise.all([
        api.get<DiscussionRun[]>("/runs"),
        api.get<ChatSession[]>("/chat-sessions"),
        api.get<AgentConfig[]>("/agents"),
        api.get<ModelConfig[]>("/models")
      ]);
      setRuns(runData);
      setSessions(sessionData);
      setAgents(agentData);
      setModels(modelData);
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "加载历史运行失败";
      setError(message);
      toast({ tone: "danger", title: "加载历史运行失败", description: message });
    } finally {
      if (mode === "initial") setLoading(false);
      else setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadAll("initial");
  }, []);

  const sessionMap = useMemo(() => Object.fromEntries(sessions.map((session) => [session.id, session])), [sessions]);
  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);

  const filteredRuns = useMemo(() => runs.filter((run) => statusFilter === "all" || run.status === statusFilter), [runs, statusFilter]);

  async function deleteRun(runId: string) {
    const run = runs.find((item) => item.id === runId);
    setBusyRunId(runId);
    try {
      await api.del(`/runs/${runId}`);
      setRuns((prev) => prev.filter((item) => item.id !== runId));
      toast({ tone: "success", title: "运行记录已删除", description: run ? `${run.id} 已从历史列表移除。` : undefined });
    } catch (err) {
      const message = err instanceof Error ? err.message : "删除运行记录失败";
      setError(message);
      toast({ tone: "danger", title: "删除失败", description: message });
    } finally {
      setBusyRunId(null);
    }
  }

  async function rerunSession(sessionId: string) {
    const session = sessions.find((item) => item.id === sessionId);
    setBusyRunId(sessionId);
    try {
      if (!session) {
        const message = "未找到对应的讨论会话。";
        setError(message);
        toast({ tone: "danger", title: "重新运行失败", description: message });
        return;
      }
      if (!hasExplicitModerator(session.agent_ids, agents)) {
        const message = "无法重新运行：该会话未显式指定 Moderator。";
        setError(message);
        toast({ tone: "danger", title: "重新运行失败", description: message });
        return;
      }
      const run = await api.post<DiscussionRun>(`/chat-sessions/${sessionId}/start`, { notify_feishu: false });
      setLastRunId(run.id);
      await loadAll();
      toast({ tone: "success", title: "已创建新的 Run", description: `${session.name} 已重新启动。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "重新运行失败";
      setError(message);
      toast({ tone: "danger", title: "重新运行失败", description: message });
    } finally {
      setBusyRunId(null);
    }
  }

  if (loading) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-[190px]" />
        <Skeleton className="h-[860px]" />
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="Run Archive" title="历史运行中心" desc="统一查看历史 Run、报告、回放与重新运行入口，保持和运行详情页一致的视觉与反馈体验。" />
        <div className="flex flex-wrap gap-2">
          <Badge>{runs.length} 条运行记录</Badge>
          <Badge tone="success">已完成 {runs.filter((item) => item.status === "finished").length}</Badge>
          <Badge tone="warn">运行中 {runs.filter((item) => item.status === "running").length}</Badge>
          <Badge tone="warn">已暂停 {runs.filter((item) => item.status === "paused").length}</Badge>
          <Badge tone="danger">失败 {runs.filter((item) => item.status === "failed").length}</Badge>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {STATUS_FILTERS.map((status) => (
            <SecondaryButton key={status} type="button" className={statusFilter === status ? "border-[var(--brand-strong)] bg-[var(--brand-soft)]" : ""} onClick={() => setStatusFilter(status)}>
              {status === "all" ? "全部" : status}
            </SecondaryButton>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <SecondaryButton type="button" loading={refreshing} onClick={() => void loadAll()}>
            刷新列表
          </SecondaryButton>
          {lastRunId ? (
            <Link href={`/runs/${lastRunId}`} className="btn-primary inline-flex items-center rounded-2xl px-4 py-2.5 text-sm font-medium text-white">
              查看最近重新运行的 Run
            </Link>
          ) : null}
        </div>
      </Card>

      {error ? <InlineAlert tone="danger" title="历史运行页有一项操作失败" description={error} /> : null}

      <Card>
        <SectionTitle eyebrow="Run List" title="运行记录" desc="支持进入详情页、回放页、重新运行和删除记录。" />
        <div className="grid gap-4">
          {filteredRuns.map((run, index) => {
            const session = sessionMap[run.session_id];
            const sessionHasModerator = session ? hasExplicitModerator(session.agent_ids, agents) : false;
            const report = run.latest_report;
            const participantInfos = (session?.agent_ids ?? []).map((agentId) => agentDirectory[agentId]).filter(Boolean);
            const busy = busyRunId === run.id || busyRunId === session?.id;

            return (
              <div key={run.id} className="fade-in-up rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5" style={{ animationDelay: `${Math.min(index * 40, 240)}ms` }}>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0 flex-1 space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="break-words text-lg font-semibold text-[var(--text)]">{session?.name ?? `Session ${run.session_id.slice(0, 8)}`}</h3>
                      <Badge tone={runTone(run.status)}>{run.status}</Badge>
                      {session && !sessionHasModerator ? <Badge tone="danger">缺少 Moderator</Badge> : null}
                    </div>

                    <p className="whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{session?.topic ?? "-"}</p>

                    <div className="flex flex-wrap gap-2">
                      {participantInfos.length ? (
                        participantInfos.map((agent) => (
                          <AgentChip key={agent.id} className="max-w-full">
                            <AgentAvatar seed={agent.id} name={agent.name} className="h-7 w-7" />
                            <span className="truncate">{agent.label}</span>
                          </AgentChip>
                        ))
                      ) : (
                        <Badge>暂无参与角色信息</Badge>
                      )}
                    </div>

                    <div className="grid gap-2 text-sm text-[var(--muted)] md:grid-cols-2">
                      <div>Run ID：{run.id}</div>
                      <div>当前轮次：{run.current_round}</div>
                      <div>开始时间：{formatDateTime(run.started_at)}</div>
                      <div>结束时间：{formatDateTime(run.ended_at)}</div>
                      {run.stop_reason ? <div className="md:col-span-2">停止原因：{run.stop_reason}</div> : null}
                      {report ? <div className="md:col-span-2">报告标题：{report.title}</div> : null}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Link href={`/runs/${run.id}`} className="btn-primary inline-flex items-center rounded-2xl px-4 py-2.5 text-sm font-medium text-white">
                      查看详情
                    </Link>
                    <Link href={`/runs/${run.id}/replay`} className="btn-secondary inline-flex items-center rounded-2xl px-4 py-2.5 text-sm font-medium">
                      回放
                    </Link>
                    {session ? (
                      <PrimaryButton type="button" loading={busy} onClick={() => void rerunSession(session.id)} disabled={!sessionHasModerator}>
                        重新运行
                      </PrimaryButton>
                    ) : null}
                    <SecondaryButton
                      type="button"
                      loading={busyRunId === run.id}
                      onClick={() => {
                        if (!window.confirm(`确认删除运行记录 ${run.id} 吗？`)) return;
                        void deleteRun(run.id);
                      }}
                    >
                      删除
                    </SecondaryButton>
                  </div>
                </div>
              </div>
            );
          })}

          {!filteredRuns.length ? (
            <EmptyState
              title={statusFilter === "all" ? "还没有历史运行记录" : `没有状态为 ${statusFilter} 的运行记录`}
              description={statusFilter === "all" ? "先去创建一个讨论会话并启动 Run，这里会自动沉淀历史记录。" : "你可以切换筛选条件，或者重新启动一个会话。"}
            />
          ) : null}
        </div>
      </Card>
    </div>
  );
}
