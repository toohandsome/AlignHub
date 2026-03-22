"use client";

import { AgentAvatar, AgentChip } from "@/components/discussion-ui";
import { EmptyState } from "@/components/ui";
import { AgentConfig } from "@/lib/api";
import { AgentDirectory } from "@/lib/discussion";

export function RunParticipantsPanel({
  participantAgents,
  agentDirectory
}: {
  participantAgents: AgentConfig[];
  agentDirectory: AgentDirectory;
}) {
  return (
    <div className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
      <div className="text-sm font-semibold text-[var(--text)]">参与角色详情</div>
      <div className="mt-3 grid gap-3">
        {participantAgents.map((agent) => {
          const info = agentDirectory[agent.id];
          return (
            <div key={agent.id} className="rounded-[24px] border border-[var(--line)] bg-[var(--panel)] p-4">
              <div className="flex items-start gap-3">
                <AgentAvatar seed={agent.id} name={agent.name} className="h-10 w-10" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-[var(--text)]">{info?.label ?? agent.name}</div>
                  <div className="text-xs text-[var(--brand-strong)]">{agent.role}</div>
                  {agent.persona ? <div className="mt-1 text-xs leading-6 text-[var(--muted)]">Persona：{agent.persona}</div> : null}

                  {agent.tool_names.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {agent.tool_names.map((name) => (
                        <AgentChip key={`${agent.id}-tool-${name}`}>
                          <span>Tool · {name}</span>
                        </AgentChip>
                      ))}
                    </div>
                  ) : null}

                  {agent.skill_names.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {agent.skill_names.map((name) => (
                        <AgentChip key={`${agent.id}-skill-${name}`}>
                          <span>Skill · {name}</span>
                        </AgentChip>
                      ))}
                    </div>
                  ) : null}

                  {agent.mcp_names.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {agent.mcp_names.map((name) => (
                        <AgentChip key={`${agent.id}-mcp-${name}`}>
                          <span>MCP · {name}</span>
                        </AgentChip>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
        {!participantAgents.length ? <EmptyState title="暂无可展示的角色详情" description="当前运行还没有加载到参与 Agent。" /> : null}
      </div>
    </div>
  );
}
