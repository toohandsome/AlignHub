"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { AgentAvatar, AgentChip } from "@/components/discussion-ui";
import { Badge, Card, Input, PrimaryButton, SecondaryButton, SectionTitle, Textarea } from "@/components/ui";
import { AgentConfig, api, ChatSession, DiscussionRun, ModelConfig } from "@/lib/api";
import { buildAgentDirectory } from "@/lib/discussion";

type SessionForm = {
  id?: string;
  name: string;
  topic: string;
  maxRounds: number;
  selectedAgents: string[];
};

const emptyForm: SessionForm = {
  name: "",
  topic: "",
  maxRounds: 10,
  selectedAgents: []
};

function sessionTone(status: string): "default" | "success" | "warn" | "danger" {
  if (status === "finished") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "paused") return "warn";
  return "default";
}

export default function SessionsPage() {
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [form, setForm] = useState<SessionForm>(emptyForm);
  const [lastRun, setLastRun] = useState<DiscussionRun | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadAll() {
    const [agentData, modelData, sessionData] = await Promise.all([
      api.get<AgentConfig[]>("/agents"),
      api.get<ModelConfig[]>("/models"),
      api.get<ChatSession[]>("/chat-sessions")
    ]);
    setAgents(agentData);
    setModels(modelData);
    setSessions(sessionData);
  }

  useEffect(() => {
    loadAll().catch((err) => setError(err.message));
  }, []);

  const editing = Boolean(form.id);
  const selectedAgentSet = useMemo(() => new Set(form.selectedAgents), [form.selectedAgents]);
  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);
  const selectedAgentDetails = useMemo(
    () =>
      form.selectedAgents
        .map((agentId) => agents.find((agent) => agent.id === agentId))
        .filter((item): item is AgentConfig => Boolean(item)),
    [agents, form.selectedAgents]
  );
  const availableAgents = useMemo(() => agents.filter((agent) => !selectedAgentSet.has(agent.id)), [agents, selectedAgentSet]);

  function resetForm() {
    setForm(emptyForm);
    setError("");
  }

  function addAgent(agentId: string) {
    setForm((prev) => (prev.selectedAgents.includes(agentId) ? prev : { ...prev, selectedAgents: [...prev.selectedAgents, agentId] }));
  }

  function removeAgent(agentId: string) {
    setForm((prev) => ({ ...prev, selectedAgents: prev.selectedAgents.filter((id) => id !== agentId) }));
  }

  function moveAgent(agentId: string, direction: -1 | 1) {
    setForm((prev) => {
      const index = prev.selectedAgents.findIndex((id) => id === agentId);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= prev.selectedAgents.length) return prev;
      const next = [...prev.selectedAgents];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return { ...prev, selectedAgents: next };
    });
  }

  async function saveSession(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = {
        name: form.name,
        topic: form.topic,
        max_rounds: form.maxRounds,
        status: "draft",
        agent_ids: form.selectedAgents
      };
      if (form.id) {
        await api.put(`/chat-sessions/${form.id}`, payload);
      } else {
        await api.post("/chat-sessions", payload);
      }
      resetForm();
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : editing ? "更新会话失败" : "创建会话失败");
    } finally {
      setLoading(false);
    }
  }

  async function startSession(sessionId: string) {
    setError("");
    try {
      const run = await api.post<DiscussionRun>(`/chat-sessions/${sessionId}/start`);
      setLastRun(run);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动讨论失败");
    }
  }

  async function deleteSession(sessionId: string) {
    if (!window.confirm("确认删除这个讨论会话吗？")) return;
    await api.del(`/chat-sessions/${sessionId}`);
    if (form.id === sessionId) resetForm();
    await loadAll();
  }

  function editSession(session: ChatSession) {
    setForm({
      id: session.id,
      name: session.name,
      topic: session.topic,
      maxRounds: session.max_rounds,
      selectedAgents: [...session.agent_ids]
    });
    setError("");
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_0.95fr]">
      <Card>
        <SectionTitle title="讨论会话列表" desc="会话仅维护议题、参与 Agent 及发言顺序；飞书群聊绑定不再在此页维护。" />
        <div className="flex flex-wrap items-center gap-3">
          <Badge>会话总数：{sessions.length}</Badge>
          <Badge tone="success">已完成：{sessions.filter((item) => item.status === "finished").length}</Badge>
          <Badge tone="warn">运行中 / 暂停：{sessions.filter((item) => ["running", "paused"].includes(item.status)).length}</Badge>
        </div>
        {lastRun ? (
          <Link href={`/runs/${lastRun.id}`} className="mt-4 block rounded-xl border border-sky-500/40 bg-sky-500/10 px-4 py-3 text-sm text-sky-500">
            最近启动的 Run：{lastRun.id}
          </Link>
        ) : null}
        {error ? <p className="mt-4 text-sm text-rose-500">{error}</p> : null}

        <div className="mt-4 grid gap-3">
          {sessions.map((session) => {
            const participantInfos = session.agent_ids
              .map((agentId) => {
                const agent = agents.find((item) => item.id === agentId);
                const info = agentDirectory[agentId];
                if (!agent || !info) return null;
                return { agent, info };
              })
              .filter((item): item is { agent: AgentConfig; info: NonNullable<(typeof agentDirectory)[string]> } => Boolean(item));

            return (
              <div key={session.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1 space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="break-words font-medium text-[var(--text)]">{session.name}</h3>
                      <Badge tone={sessionTone(session.status)}>{session.status}</Badge>
                      <Badge>最大轮次：{session.max_rounds}</Badge>
                    </div>

                    <p className="whitespace-pre-wrap break-words text-sm text-[var(--text)]">{session.topic}</p>

                    <div className="grid gap-2">
                      {participantInfos.map(({ agent, info }, index) => (
                        <div key={agent.id} className="flex items-center gap-3 rounded-xl border border-[var(--line)] bg-[var(--panel)] px-3 py-2">
                          <Badge>{index + 1}</Badge>
                          <AgentAvatar seed={agent.id} name={agent.name} className="h-8 w-8" />
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm text-[var(--text)]">{info.label}</div>
                            {agent.is_moderator ? <div className="text-xs text-amber-500">Moderator</div> : null}
                          </div>
                        </div>
                      ))}
                      {!participantInfos.length ? <p className="text-sm text-[var(--muted)]">当前会话尚未选择参与 Agent。</p> : null}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <PrimaryButton type="button" onClick={() => startSession(session.id)}>
                      启动
                    </PrimaryButton>
                    <PrimaryButton type="button" onClick={() => editSession(session)}>
                      编辑
                    </PrimaryButton>
                    <SecondaryButton type="button" onClick={() => deleteSession(session.id)}>
                      删除
                    </SecondaryButton>
                  </div>
                </div>
              </div>
            );
          })}
          {!sessions.length ? <p className="text-sm text-[var(--muted)]">暂无讨论会话，请先创建。</p> : null}
        </div>
      </Card>

      <Card>
        <SectionTitle title={editing ? "编辑讨论会话" : "创建讨论会话"} desc="在这里明确参与 Agent 及发言顺序；列表顺序就是后端 speak_order。" />
        <form onSubmit={saveSession} className="space-y-4">
          <Input placeholder="会话名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          <Textarea placeholder="讨论主题 / 业务问题" value={form.topic} onChange={(event) => setForm({ ...form, topic: event.target.value })} />
          <Input
            type="number"
            min={1}
            max={50}
            value={form.maxRounds}
            onChange={(event) => setForm({ ...form, maxRounds: Number(event.target.value || 1) })}
          />

          <div className="space-y-2">
            <div className="text-sm text-[var(--muted)]">已选 Agent（按发言顺序）</div>
            <div className="grid gap-2">
              {selectedAgentDetails.map((agent, index) => {
                const info = agentDirectory[agent.id];
                return (
                  <div key={agent.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3">
                    <Badge>{index + 1}</Badge>
                    <AgentAvatar seed={agent.id} name={agent.name} className="h-9 w-9" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-[var(--text)]">{info?.label ?? agent.name}</div>
                      <div className="truncate text-xs text-[var(--muted)]">
                        {agent.role}
                        {agent.is_moderator ? " · Moderator" : ""}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <SecondaryButton type="button" onClick={() => moveAgent(agent.id, -1)} disabled={index === 0}>
                        上移
                      </SecondaryButton>
                      <SecondaryButton type="button" onClick={() => moveAgent(agent.id, 1)} disabled={index === selectedAgentDetails.length - 1}>
                        下移
                      </SecondaryButton>
                      <SecondaryButton type="button" onClick={() => removeAgent(agent.id)}>
                        移除
                      </SecondaryButton>
                    </div>
                  </div>
                );
              })}
              {!selectedAgentDetails.length ? <p className="text-sm text-[var(--muted)]">尚未选择 Agent。至少需要 1 个参与者。</p> : null}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-sm text-[var(--muted)]">可添加 Agent</div>
            <div className="grid gap-2">
              {availableAgents.map((agent) => {
                const info = agentDirectory[agent.id];
                return (
                  <div key={agent.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3">
                    <AgentAvatar seed={agent.id} name={agent.name} className="h-9 w-9" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-[var(--text)]">{info?.label ?? agent.name}</div>
                      <div className="truncate text-xs text-[var(--muted)]">
                        {agent.role}
                        {agent.is_moderator ? " · Moderator" : ""}
                      </div>
                    </div>
                    <PrimaryButton type="button" onClick={() => addAgent(agent.id)}>
                      添加
                    </PrimaryButton>
                  </div>
                );
              })}
              {!availableAgents.length ? <p className="text-sm text-[var(--muted)]">所有 Agent 都已经加入当前会话。</p> : null}
            </div>
          </div>

          <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--muted)]">
            飞书群聊绑定已从本页移除。若确需推送，请在飞书集成链路中按会话或命令侧主动建立绑定。
          </div>

          <div className="flex flex-wrap gap-3">
            <PrimaryButton type="submit" disabled={loading || !form.name || !form.topic || form.selectedAgents.length === 0}>
              {loading ? "保存中..." : editing ? "保存修改" : "创建会话"}
            </PrimaryButton>
            {editing ? (
              <SecondaryButton type="button" onClick={resetForm}>
                取消编辑
              </SecondaryButton>
            ) : null}
          </div>
        </form>
      </Card>
    </div>
  );
}
