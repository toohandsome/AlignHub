"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AgentAvatar } from "@/components/discussion-ui";
import { Badge, Card, EmptyState, Field, InlineAlert, Input, PrimaryButton, SecondaryButton, SectionTitle, Skeleton, Textarea, useToast } from "@/components/ui";
import { AgentConfig, api, ChatSession, DiscussionRun, ModelConfig } from "@/lib/api";
import { buildAgentDirectory } from "@/lib/discussion";
import { focusField } from "@/lib/form-feedback";

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

function hasExplicitModerator(agentIds: string[], agents: AgentConfig[]) {
  return agentIds.some((agentId) => agents.find((agent) => agent.id === agentId)?.is_moderator);
}

function sessionTone(status: string): "default" | "success" | "warn" | "danger" {
  if (status === "finished") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "paused") return "warn";
  return "default";
}

export default function SessionsPage() {
  const { toast } = useToast();
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [form, setForm] = useState<SessionForm>(emptyForm);
  const [lastRun, setLastRun] = useState<DiscussionRun | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [busySessionId, setBusySessionId] = useState<string | null>(null);

  async function loadAll(showLoader = false) {
    if (showLoader) setBootstrapping(true);
    try {
      const [agentData, modelData, sessionData] = await Promise.all([
        api.get<AgentConfig[]>("/agents"),
        api.get<ModelConfig[]>("/models"),
        api.get<ChatSession[]>("/chat-sessions")
      ]);
      setAgents(agentData);
      setModels(modelData);
      setSessions(sessionData);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载会话数据失败");
    } finally {
      if (showLoader) setBootstrapping(false);
    }
  }

  useEffect(() => {
    void loadAll(true);
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
  const formHasModerator = useMemo(() => hasExplicitModerator(form.selectedAgents, agents), [agents, form.selectedAgents]);

  const formErrors = useMemo(
    () => ({
      name: form.name.trim() ? "" : "请输入会话名称",
      topic: form.topic.trim() ? "" : "请输入讨论主题",
      maxRounds: form.maxRounds > 0 ? "" : "最大轮次必须大于 0",
      selectedAgents: form.selectedAgents.length > 0 ? "" : "至少选择 1 个参与 Agent",
      moderator: formHasModerator ? "" : "必须显式包含至少 1 个 Moderator"
    }),
    [form, formHasModerator]
  );

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

  async function saveSession() {
    setLoading(true);
    setError("");
    try {
      const payload = {
        name: form.name.trim(),
        topic: form.topic.trim(),
        max_rounds: form.maxRounds,
        status: "draft",
        agent_ids: form.selectedAgents
      };
      if (form.id) {
        await api.put(`/chat-sessions/${form.id}`, payload);
      } else {
        await api.post("/chat-sessions", payload);
      }
      const sessionName = form.name.trim();
      resetForm();
      await loadAll();
      toast({ tone: "success", title: form.id ? "会话已更新" : "会话已创建", description: `${sessionName} 已可直接启动运行。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : editing ? "更新会话失败" : "创建会话失败";
      setError(message);
      toast({ tone: "danger", title: "保存会话失败", description: message });
      throw err;
    } finally {
      setLoading(false);
    }
  }

  async function startSession(sessionId: string) {
    setBusySessionId(sessionId);
    setError("");
    try {
      const session = sessions.find((item) => item.id === sessionId);
      if (!session) {
        const message = "未找到对应的讨论会话。";
        setError(message);
        toast({ tone: "danger", title: "启动失败", description: message });
        return;
      }
      if (!hasExplicitModerator(session.agent_ids, agents)) {
        const message = "无法启动：当前会话未包含 Moderator。";
        setError(message);
        toast({ tone: "danger", title: "启动失败", description: message });
        return;
      }
      const run = await api.post<DiscussionRun>(`/chat-sessions/${sessionId}/start`);
      setLastRun(run);
      await loadAll();
      toast({ tone: "success", title: "讨论已启动", description: `${session.name} 已创建 Run。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "启动讨论失败";
      setError(message);
      toast({ tone: "danger", title: "启动讨论失败", description: message });
    } finally {
      setBusySessionId(null);
    }
  }

  async function deleteSession(sessionId: string) {
    const target = sessions.find((item) => item.id === sessionId);
    setBusySessionId(sessionId);
    try {
      await api.del(`/chat-sessions/${sessionId}`);
      if (form.id === sessionId) resetForm();
      await loadAll();
      toast({ tone: "success", title: "会话已删除", description: target?.name ? `${target.name} 已从列表移除。` : undefined });
    } catch (err) {
      const message = err instanceof Error ? err.message : "删除会话失败";
      setError(message);
      toast({ tone: "danger", title: "删除会话失败", description: message });
    } finally {
      setBusySessionId(null);
    }
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
    toast({ tone: "default", title: "已载入会话", description: `正在编辑 ${session.name}` });
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (formErrors.name) {
      focusField("name");
      return;
    }
    if (formErrors.topic) {
      focusField("topic");
      return;
    }
    if (formErrors.maxRounds) {
      focusField("maxRounds");
      return;
    }
    if (formErrors.selectedAgents || formErrors.moderator) {
      setError(formErrors.selectedAgents || formErrors.moderator);
      return;
    }
    await saveSession();
  }

  if (bootstrapping) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1.15fr_0.95fr]">
        <Skeleton className="h-[820px]" />
        <Skeleton className="h-[980px]" />
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="Collaboration Flow" title="讨论会话工作台" desc="创建会话时即可确定发言顺序、主持人存在性与启动入口，减少二次操作。" />
        <div className="flex flex-wrap gap-2">
          <Badge>{sessions.length} 个会话</Badge>
          <Badge tone="success">已完成 {sessions.filter((item) => item.status === "finished").length}</Badge>
          <Badge tone="warn">运行中 / 暂停 {sessions.filter((item) => ["running", "paused"].includes(item.status)).length}</Badge>
        </div>
        {lastRun ? (
          <Link href={`/runs/${lastRun.id}`} className="mt-4 inline-flex rounded-2xl border border-[var(--line-strong)] bg-[var(--brand-soft)] px-4 py-3 text-sm font-medium text-[var(--brand-strong)]">
            查看最近启动的 Run：{lastRun.id}
          </Link>
        ) : null}
      </Card>

      {error ? <InlineAlert tone="danger" title="会话页面操作失败" description={error} /> : null}

      <div className="grid gap-6 lg:grid-cols-[1.15fr_0.95fr]">
        <Card>
          <SectionTitle eyebrow="Sessions" title="讨论会话列表" desc="会话只维护主题、参与 Agent 与发言顺序；飞书绑定不再在本页维护。" />
          <div className="grid gap-4">
            {sessions.map((session) => {
              const sessionHasModerator = hasExplicitModerator(session.agent_ids, agents);
              const participantInfos = session.agent_ids
                .map((agentId) => {
                  const agent = agents.find((item) => item.id === agentId);
                  const info = agentDirectory[agentId];
                  if (!agent || !info) return null;
                  return { agent, info };
                })
                .filter((item): item is { agent: AgentConfig; info: NonNullable<(typeof agentDirectory)[string]> } => Boolean(item));

              return (
                <div key={session.id} className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0 flex-1 space-y-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="break-words text-lg font-semibold text-[var(--text)]">{session.name}</h3>
                        <Badge tone={sessionTone(session.status)}>{session.status}</Badge>
                        <Badge>最大轮次：{session.max_rounds}</Badge>
                        {!sessionHasModerator ? <Badge tone="danger">缺少 Moderator</Badge> : null}
                      </div>

                      <p className="whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{session.topic}</p>

                      <div className="grid gap-2">
                        {participantInfos.map(({ agent, info }, index) => (
                          <div key={agent.id} className="flex items-center gap-3 rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-3 py-2.5">
                            <Badge>{index + 1}</Badge>
                            <AgentAvatar seed={agent.id} name={agent.name} className="h-8 w-8" />
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm text-[var(--text)]">{info.label}</div>
                              <div className="truncate text-xs text-[var(--muted)]">
                                {agent.role}
                                {agent.is_moderator ? " · Moderator" : ""}
                              </div>
                            </div>
                          </div>
                        ))}
                        {!participantInfos.length ? <EmptyState title="当前会话尚未选择参与 Agent" description="可在右侧编辑区添加角色并调整发言顺序。" /> : null}
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <PrimaryButton type="button" loading={busySessionId === session.id} onClick={() => void startSession(session.id)} disabled={!sessionHasModerator}>
                        启动
                      </PrimaryButton>
                      <PrimaryButton type="button" onClick={() => editSession(session)}>
                        编辑
                      </PrimaryButton>
                      <SecondaryButton
                        type="button"
                        loading={busySessionId === session.id}
                        onClick={() => {
                          if (!window.confirm(`确认删除会话 “${session.name}” 吗？`)) return;
                          void deleteSession(session.id);
                        }}
                      >
                        删除
                      </SecondaryButton>
                    </div>
                  </div>
                  {!sessionHasModerator ? <div className="mt-3 text-sm text-rose-500">当前会话未显式指定 Moderator，因此暂时不能启动讨论。</div> : null}
                </div>
              );
            })}
            {!sessions.length ? <EmptyState title="还没有讨论会话" description="先在右侧创建会话，并加入至少一个 Moderator 后即可启动。" /> : null}
          </div>
        </Card>

        <Card>
          <SectionTitle eyebrow="Session Builder" title={editing ? "编辑讨论会话" : "创建讨论会话"} desc="明确参与 Agent 与发言顺序后，可直接从左侧一键启动。" />
          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="会话名称" required error={formErrors.name}>
              <Input name="name" placeholder="例如：Q2 增长策略讨论" value={form.name} invalid={Boolean(formErrors.name)} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </Field>
            <Field label="讨论主题" required error={formErrors.topic}>
              <Textarea name="topic" placeholder="输入业务问题、上下文与预期结论" value={form.topic} invalid={Boolean(formErrors.topic)} onChange={(event) => setForm({ ...form, topic: event.target.value })} />
            </Field>
            <Field label="最大轮次" error={formErrors.maxRounds}>
              <Input
                name="maxRounds"
                type="number"
                min={1}
                max={50}
                value={form.maxRounds}
                invalid={Boolean(formErrors.maxRounds)}
                onChange={(event) => setForm({ ...form, maxRounds: Number(event.target.value || 1) })}
              />
            </Field>

            <div className="space-y-3 rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
              <div>
                <div className="text-sm font-medium text-[var(--text)]">已选 Agent（按发言顺序）</div>
                <div className="mt-1 text-sm text-[var(--muted)]">顺序即 speak_order，可直接在此调整，无需进入二级编辑。</div>
              </div>
              <div className="grid gap-2">
                {selectedAgentDetails.map((agent, index) => {
                  const info = agentDirectory[agent.id];
                  return (
                    <div key={agent.id} className="flex flex-wrap items-center gap-2 rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-3 py-3">
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
                {!selectedAgentDetails.length ? <EmptyState title="尚未选择 Agent" description="至少选择 1 个角色，并确保其中包含 Moderator。" /> : null}
              </div>
              {!formHasModerator ? <div className="text-sm text-rose-500">必须显式选择至少 1 个已标记为 Moderator 的 Agent。</div> : null}
            </div>

            <div className="space-y-3 rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
              <div>
                <div className="text-sm font-medium text-[var(--text)]">可添加 Agent</div>
                <div className="mt-1 text-sm text-[var(--muted)]">点击即可加入会话，减少来回切换表单的步骤。</div>
              </div>
              <div className="grid gap-2">
                {availableAgents.map((agent) => {
                  const info = agentDirectory[agent.id];
                  return (
                    <div key={agent.id} className="flex flex-wrap items-center gap-2 rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-3 py-3">
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
                {!availableAgents.length ? <EmptyState title="所有 Agent 都已加入当前会话" description="如需调整顺序，可在上方已选列表中完成。" /> : null}
              </div>
            </div>

            <div className="rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-4 text-sm leading-7 text-[var(--muted)]">
              飞书群聊绑定已从本页移除。若需要在群内协同讨论，请前往飞书集成链路按会话或命令侧建立绑定。
            </div>

            <div className="flex flex-wrap gap-3">
              <PrimaryButton type="submit" loading={loading}>
                {editing ? "保存会话" : "创建会话"}
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
    </div>
  );
}
