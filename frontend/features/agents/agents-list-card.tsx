"use client";

import { AgentAvatar, AgentChip } from "@/components/discussion-ui";
import { Badge, Card, EmptyState, PrimaryButton, SecondaryButton, SectionTitle } from "@/components/ui";
import { AgentConfig, ModelConfig } from "@/lib/api";
import { AgentDirectory } from "@/lib/discussion";

type Props = {
  agents: AgentConfig[];
  busyAgentId: string | null;
  agentDirectory: AgentDirectory;
  modelMap: Record<string, ModelConfig>;
  onEdit: (agent: AgentConfig) => void;
  onCopy: (agent: AgentConfig) => Promise<void>;
  onDelete: (agentId: string) => Promise<void>;
};

export function AgentsListCard({ agents, busyAgentId, agentDirectory, modelMap, onEdit, onCopy, onDelete }: Props) {
  return (
    <Card>
      <SectionTitle eyebrow="Role Library" title="Agent 列表" desc="查看角色画像、能力挂载与主持人分布，直接在当前页复制或编辑。" />
      <div className="grid gap-4">
        {agents.map((agent) => {
          const info = agentDirectory[agent.id];
          const model = modelMap[agent.model_id];
          const isBusy = busyAgentId === agent.id;
          return (
            <div key={agent.id} className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-3">
                    <AgentAvatar seed={agent.id} name={agent.name} className="h-12 w-12" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-lg font-semibold text-[var(--text)]">{info?.label ?? agent.name}</h3>
                        {agent.is_moderator ? <Badge tone="warn">Moderator</Badge> : null}
                      </div>
                      <p className="mt-1 text-sm text-[var(--brand-strong)]">{agent.role}</p>
                      {agent.persona ? <p className="mt-2 text-sm text-[var(--muted)]">人格：{agent.persona}</p> : null}
                    </div>
                  </div>

                  <div className="mt-4 grid gap-2 text-sm text-[var(--muted)] md:grid-cols-2">
                    <div>模型：{model?.model_name ?? agent.model_id}</div>
                    <div>memory_strategy：{agent.memory_strategy}</div>
                    <div>max_steps：{agent.max_steps}</div>
                    <div>工具数量：{agent.tool_names.length}</div>
                    <div>Skill 数量：{agent.skill_names.length}</div>
                    <div>MCP 数量：{agent.mcp_names.length}</div>
                    <div className="md:col-span-2">
                      飞书机器人：
                      {agent.feishu_bot_enabled ? `已启用${agent.feishu_bot_name ? `（${agent.feishu_bot_name}）` : ""}` : "未配置"}
                      {agent.feishu_bot_receive_enabled ? " · 可接收事件" : ""}
                    </div>
                  </div>

                  {agent.extra_config_json ? <pre className="mt-4 overflow-x-auto rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(agent.extra_config_json, null, 2)}</pre> : null}
                  <p className="mt-4 whitespace-pre-wrap break-words rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm leading-7 text-[var(--muted)]">{agent.system_prompt}</p>

                  {agent.tool_names.length ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {agent.tool_names.map((tool) => (
                        <AgentChip key={tool}>
                          <span className="truncate">Tool · {tool}</span>
                        </AgentChip>
                      ))}
                    </div>
                  ) : null}

                  {agent.skill_names.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {agent.skill_names.map((name) => (
                        <AgentChip key={name}>
                          <span className="truncate">Skill · {name}</span>
                        </AgentChip>
                      ))}
                    </div>
                  ) : null}

                  {agent.mcp_names.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {agent.mcp_names.map((name) => (
                        <AgentChip key={name}>
                          <span className="truncate">MCP · {name}</span>
                        </AgentChip>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className="flex flex-wrap gap-2">
                  <PrimaryButton type="button" onClick={() => onEdit(agent)}>
                    编辑
                  </PrimaryButton>
                  <PrimaryButton type="button" loading={isBusy} onClick={() => void onCopy(agent)}>
                    复制
                  </PrimaryButton>
                  <SecondaryButton
                    type="button"
                    loading={isBusy}
                    onClick={() => {
                      if (!window.confirm(`确认删除 Agent “${agent.name}” 吗？`)) return;
                      void onDelete(agent.id);
                    }}
                  >
                    删除
                  </SecondaryButton>
                </div>
              </div>
            </div>
          );
        })}
        {!agents.length ? <EmptyState title="还没有 Agent" description="建议先创建至少一个主持人角色和若干执行角色，再去创建讨论会话。" /> : null}
      </div>
    </Card>
  );
}
