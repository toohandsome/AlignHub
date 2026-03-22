"use client";

import { useMemo, useState } from "react";

import { AgentAvatar, AgentChip } from "@/components/discussion-ui";
import { Badge, EmptyState } from "@/components/ui";
import { AgentConfig, ChatSession } from "@/lib/api";
import { AgentDirectory } from "@/lib/discussion";

type Props = {
  session: ChatSession | null;
  participantAgents: AgentConfig[];
  agentDirectory: AgentDirectory;
};

function MetaStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-[22px] border border-[var(--line)] bg-[var(--panel)] px-3 py-3">
      <div className="text-[11px] text-[var(--muted)]">{label}</div>
      <div className="mt-1 text-sm font-semibold text-[var(--text)]">{value}</div>
    </div>
  );
}

export function RunSessionOverview({ session, participantAgents, agentDirectory }: Props) {
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null);

  const activeAgent = useMemo(() => {
    if (!participantAgents.length) return null;
    return participantAgents.find((agent) => agent.id === activeAgentId) ?? participantAgents[0];
  }, [activeAgentId, participantAgents]);

  const hasModerator = participantAgents.some((agent) => agent.is_moderator);

  return (
    <div className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--brand-strong)]">Session Snapshot</div>
          <div className="mt-2 break-words text-xl font-semibold text-[var(--text)]">{session?.name ?? "运行上下文加载中"}</div>

          <div className="mt-4 text-xs text-[var(--muted)]">讨论 Topic</div>
          <div className="mt-1 whitespace-pre-wrap break-words text-sm leading-7 text-[var(--text)]">{session?.topic ?? "-"}</div>

          <div className="mt-5 grid gap-2 sm:grid-cols-3">
            <MetaStat label="参与 Agent" value={participantAgents.length} />
            <MetaStat label="Moderator" value={hasModerator ? "已配置" : "未配置"} />
            <MetaStat label="最大轮次" value={session?.max_rounds ?? "-"} />
          </div>

          <div className="mt-5 text-xs text-[var(--muted)]">参与角色</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {participantAgents.map((agent) => {
              const info = agentDirectory[agent.id];
              const active = activeAgent?.id === agent.id;
              return (
                <button
                  key={agent.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setActiveAgentId(agent.id)}
                  onMouseEnter={() => setActiveAgentId(agent.id)}
                  onFocus={() => setActiveAgentId(agent.id)}
                  className="min-w-0 text-left"
                >
                  <AgentChip className={active ? "border-[var(--brand-strong)] bg-[var(--brand-soft)] text-[var(--brand-strong)] shadow-[0_14px_40px_rgba(79,124,255,0.14)]" : "transition hover:border-[var(--brand)]"}>
                    <AgentAvatar seed={agent.id} name={agent.name} className="h-7 w-7" />
                    <span className="truncate">{info?.label ?? agent.name}</span>
                    {agent.is_moderator ? <Badge tone="warn">Moderator</Badge> : null}
                  </AgentChip>
                </button>
              );
            })}
            {!participantAgents.length ? <EmptyState title="暂无参与角色" description="当前会话还没有关联到可展示的 Agent。" /> : null}
          </div>
        </div>

        <div className="min-w-0 self-start rounded-[24px] border border-[var(--line)] bg-[var(--panel)] p-4 xl:max-h-[30rem] xl:overflow-y-auto">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--brand-strong)]">Active Agent</div>
          {activeAgent ? (
            <>
              <div className="mt-3 flex items-start gap-3">
                <AgentAvatar seed={activeAgent.id} name={activeAgent.name} className="h-11 w-11" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="truncate text-sm font-semibold text-[var(--text)]">{activeAgent.name}</div>
                    {activeAgent.is_moderator ? <Badge tone="warn">Moderator</Badge> : null}
                  </div>
                  <div className="mt-1 text-xs font-medium text-[var(--brand-strong)]">{activeAgent.role}</div>
                  <div className="mt-2 text-xs leading-6 text-[var(--muted)]">{activeAgent.persona || "未配置 Persona"}</div>
                </div>
              </div>

              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                <MetaStat label="Tool" value={activeAgent.tool_names.length} />
                <MetaStat label="Skill" value={activeAgent.skill_names.length} />
                <MetaStat label="MCP" value={activeAgent.mcp_names.length} />
              </div>

              {activeAgent.tool_names.length ? (
                <div className="mt-4">
                  <div className="mb-2 text-[11px] text-[var(--muted)]">Tools</div>
                  <div className="flex flex-wrap gap-2">
                    {activeAgent.tool_names.map((name) => (
                      <AgentChip key={`${activeAgent.id}-tool-${name}`} className="bg-transparent text-xs">
                        <span>{name}</span>
                      </AgentChip>
                    ))}
                  </div>
                </div>
              ) : null}

              {activeAgent.skill_names.length ? (
                <div className="mt-4">
                  <div className="mb-2 text-[11px] text-[var(--muted)]">Skills</div>
                  <div className="flex flex-wrap gap-2">
                    {activeAgent.skill_names.map((name) => (
                      <AgentChip key={`${activeAgent.id}-skill-${name}`} className="bg-transparent text-xs">
                        <span>{name}</span>
                      </AgentChip>
                    ))}
                  </div>
                </div>
              ) : null}

              {activeAgent.mcp_names.length ? (
                <div className="mt-4">
                  <div className="mb-2 text-[11px] text-[var(--muted)]">MCP</div>
                  <div className="flex flex-wrap gap-2">
                    {activeAgent.mcp_names.map((name) => (
                      <AgentChip key={`${activeAgent.id}-mcp-${name}`} className="bg-transparent text-xs">
                        <span>{name}</span>
                      </AgentChip>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <div className="mt-4">
              <EmptyState title="暂无可展示角色详情" description="当会话成功关联 Agent 后，这里会展示该角色的能力画像。" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
