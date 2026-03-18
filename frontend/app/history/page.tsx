"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AgentAvatar, AgentChip } from "@/components/discussion-ui";
import { Badge, Card, PrimaryButton, SecondaryButton, SectionTitle } from "@/components/ui";
import { AgentConfig, api, ChatSession, DiscussionRun, ModelConfig } from "@/lib/api";
import { buildAgentDirectory } from "@/lib/discussion";

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function runTone(status: string): "default" | "success" | "warn" | "danger" {
  if (status === "finished") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "paused") return "warn";
  return "default";
}

export default function HistoryPage() {
  const [runs, setRuns] = useState<DiscussionRun[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastRunId, setLastRunId] = useState("");

  /**
   * 历史页要把 run、session、agent、model 汇总后才能渲染完整卡片，
   * 因此这里统一做并行加载。
   */
  async function loadAll() {
    setLoading(true);
    setError("");
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载历史会话失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  const sessionMap = useMemo(() => Object.fromEntries(sessions.map((session) => [session.id, session])), [sessions]);
  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);

  const filteredRuns = useMemo(
    () => runs.filter((run) => statusFilter === "all" || run.status === statusFilter),
    [runs, statusFilter]
  );

  async function deleteRun(runId: string) {
    if (!window.confirm("确认删除这条历史运行记录吗？")) return;
    await api.del(`/runs/${runId}`);
    setRuns((prev) => prev.filter((run) => run.id !== runId));
  }

  /**
   * 历史重跑实际上是对原 session 再次调用 start。
   * 这里保留最后一次新 run 的 id，便于用户直接跳转。
   */
  async function rerunSession(sessionId: string) {
    try {
      setError("");
      const run = await api.post<DiscussionRun>(`/chat-sessions/${sessionId}/start`, { notify_feishu: false });
      setLastRunId(run.id);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新运行失败");
    }
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle title="历史会话管理" desc="统一查看历史运行、报告、回放、重跑与删除记录。" />
        <div className="flex flex-wrap items-center gap-3">
          <Badge>总运行数：{runs.length}</Badge>
          <Badge tone="success">已完成：{runs.filter((item) => item.status === "finished").length}</Badge>
          <Badge tone="warn">运行中：{runs.filter((item) => item.status === "running").length}</Badge>
          <Badge tone="warn">已暂停：{runs.filter((item) => item.status === "paused").length}</Badge>
          <Badge tone="danger">失败：{runs.filter((item) => item.status === "failed").length}</Badge>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {["all", "finished", "running", "paused", "failed", "stopped", "draft"].map((status) => (
            <SecondaryButton key={status} type="button" className={statusFilter === status ? "border-sky-400" : ""} onClick={() => setStatusFilter(status)}>
              {status === "all" ? "全部" : status}
            </SecondaryButton>
          ))}
        </div>
        {lastRunId ? (
          <Link href={`/runs/${lastRunId}`} className="mt-4 block rounded-xl border border-sky-500/40 bg-sky-500/10 px-4 py-3 text-sm text-sky-500">
            跳转到最近重新运行的 Run：{lastRunId}
          </Link>
        ) : null}
        {error ? <p className="mt-3 text-sm text-rose-500">{error}</p> : null}
      </Card>

      <Card>
        <SectionTitle title="运行历史列表" desc="支持进入详情页、回放页、重新运行和删除记录。" />
        <div className="grid gap-3">
          {filteredRuns.map((run) => {
            const session = sessionMap[run.session_id];
            const report = run.latest_report;
            const participantInfos = (session?.agent_ids ?? []).map((agentId) => agentDirectory[agentId]).filter(Boolean);

            return (
              <div key={run.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1 space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="break-words font-medium text-[var(--text)]">{session?.name ?? `Session ${run.session_id.slice(0, 8)}`}</h3>
                      <Badge tone={runTone(run.status)}>{run.status}</Badge>
                    </div>

                    <p className="whitespace-pre-wrap break-words text-sm text-[var(--text)]">{session?.topic ?? "-"}</p>

                    <div className="flex flex-wrap gap-2">
                      {participantInfos.map((agent) => (
                        <AgentChip key={agent!.id} className="max-w-full">
                          <AgentAvatar seed={agent!.id} name={agent!.name} className="h-7 w-7" />
                          <span className="truncate">{agent!.label}</span>
                        </AgentChip>
                      ))}
                    </div>

                    <div className="grid gap-1 text-xs text-[var(--muted)]">
                      <div>Run ID：{run.id}</div>
                      <div>当前轮次：{run.current_round}</div>
                      <div>开始时间：{formatDateTime(run.started_at)}</div>
                      <div>结束时间：{formatDateTime(run.ended_at)}</div>
                      {run.stop_reason ? <div>停止原因：{run.stop_reason}</div> : null}
                      {report ? <div>报告标题：{report.title}</div> : null}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Link href={`/runs/${run.id}`} className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-sky-400">
                      查看详情
                    </Link>
                    <Link href={`/runs/${run.id}/replay`} className="rounded-xl border border-[var(--line)] bg-[var(--panel)] px-4 py-2 text-sm text-[var(--text)] transition hover:border-sky-400">
                      回放
                    </Link>
                    {session ? (
                      <PrimaryButton type="button" onClick={() => rerunSession(session.id)}>
                        重新运行
                      </PrimaryButton>
                    ) : null}
                    <SecondaryButton type="button" onClick={() => loadAll()}>
                      刷新
                    </SecondaryButton>
                    <SecondaryButton type="button" onClick={() => deleteRun(run.id)}>
                      删除
                    </SecondaryButton>
                  </div>
                </div>
              </div>
            );
          })}

          {!filteredRuns.length ? <p className="text-sm text-[var(--muted)]">{loading ? "加载中..." : "暂无符合条件的历史运行记录。"}</p> : null}
        </div>
      </Card>
    </div>
  );
}
