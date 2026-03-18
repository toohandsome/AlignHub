"use client";

import { AgentAvatar, AgentChip } from "@/components/discussion-ui";
import { Card, PrimaryButton, SecondaryButton, SectionTitle } from "@/components/ui";
import { AgentConfig, ModelConfig } from "@/lib/api";
import { AgentDirectory } from "@/lib/discussion";

type Props = {
  agents: AgentConfig[];
  agentDirectory: AgentDirectory;
  modelMap: Record<string, ModelConfig>;
  onEdit: (agent: AgentConfig) => void;
  onCopy: (agent: AgentConfig) => Promise<void>;
  onDelete: (agentId: string) => Promise<void>;
};

export function AgentsListCard({ agents, agentDirectory, modelMap, onEdit, onCopy, onDelete }: Props) {
  return (
    <Card>
      <SectionTitle title="Agent 列表" desc="展示完整 Agent 运行配置，包括 memory_strategy / max_steps / Reporter 等字段。" />
      <div className="grid gap-3">
        {agents.map((agent) => {
          const info = agentDirectory[agent.id];
          const model = modelMap[agent.model_id];
          return (
            <div key={agent.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-3">
                    <AgentAvatar seed={agent.id} name={agent.name} className="h-11 w-11" />
                    <div className="min-w-0 flex-1">
                      <h3 className="truncate font-medium text-[var(--text)]">{info?.label ?? agent.name}</h3>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm text-sky-500">{agent.role}</p>
                        {agent.is_moderator ? <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-600 dark:text-amber-300">Moderator</span> : null}
                        {agent.is_reporter ? <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-300">Reporter</span> : null}
                      </div>
                      {agent.persona ? <p className="mt-1 truncate text-xs text-[var(--muted)]">人格：{agent.persona}</p> : null}
                    </div>
                  </div>

                  <div className="mt-3 grid gap-1 text-xs text-[var(--muted)]">
                    <div>模型：{model?.model_name ?? agent.model_id}</div>
                    <div>memory_strategy：{agent.memory_strategy}</div>
                    <div>max_steps：{agent.max_steps}</div>
                    <div>工具数量：{agent.tool_names.length}</div>
                    <div>Skill 数量：{agent.skill_names.length}</div>
                    <div>MCP 数量：{agent.mcp_names.length}</div>
                    <div>
                      飞书机器人：
                      {agent.feishu_bot_enabled ? `已启用${agent.feishu_bot_name ? `（${agent.feishu_bot_name}）` : ""}` : "未配置"}
                      {agent.feishu_bot_receive_enabled ? " · 可接收事件" : ""}
                    </div>
                  </div>

                  {agent.extra_config_json ? (
                    <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(agent.extra_config_json, null, 2)}</pre>
                  ) : null}
                  <p className="mt-3 whitespace-pre-wrap break-words text-sm text-[var(--muted)]">{agent.system_prompt}</p>

                  {agent.tool_names.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
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
                  <PrimaryButton type="button" onClick={() => void onCopy(agent)}>
                    复制
                  </PrimaryButton>
                  <SecondaryButton
                    type="button"
                    onClick={() => {
                      if (!window.confirm("确认删除这个 Agent 吗？")) return;
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
        {!agents.length ? <p className="text-sm text-[var(--muted)]">暂无 Agent，请先创建。</p> : null}
      </div>
    </Card>
  );
}
