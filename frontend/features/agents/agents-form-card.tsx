"use client";

import Link from "next/link";
import { type FormEvent } from "react";

import { Card, Input, PrimaryButton, SecondaryButton, SectionTitle, Select, Textarea } from "@/components/ui";
import { MCPServerConfig, ModelConfig, SkillConfig, ToolDef } from "@/lib/api";

import { AgentForm } from "./use-agents-page";

type Props = {
  editing: boolean;
  form: AgentForm;
  setForm: (value: AgentForm) => void;
  models: ModelConfig[];
  tools: ToolDef[];
  skills: SkillConfig[];
  mcps: MCPServerConfig[];
  selectedTools: Set<string>;
  selectedSkills: Set<string>;
  selectedMcps: Set<string>;
  loading: boolean;
  error: string;
  onSubmit: (event: FormEvent) => Promise<void>;
  onReset: () => void;
};

export function AgentsFormCard({
  editing,
  form,
  setForm,
  models,
  tools,
  skills,
  mcps,
  selectedTools,
  selectedSkills,
  selectedMcps,
  loading,
  error,
  onSubmit,
  onReset,
}: Props) {
  return (
    <Card>
      <SectionTitle title={editing ? "编辑 Agent" : "创建 Agent"} desc="补全 memory_strategy / max_steps / Reporter / extra_config_json 等配置项。" />
      <form onSubmit={onSubmit} className="space-y-3">
        <Input placeholder="Agent 名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input placeholder="角色" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
        <Input placeholder="人格 / Persona" value={form.persona} onChange={(e) => setForm({ ...form, persona: e.target.value })} />
        <Textarea placeholder="System Prompt" value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />

        <div className="grid gap-3 md:grid-cols-2">
          <Select value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })}>
            <option value="">选择模型</option>
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.model_name}
              </option>
            ))}
          </Select>
          <Select value={form.memory_strategy} onChange={(e) => setForm({ ...form, memory_strategy: e.target.value })}>
            <option value="in_memory">in_memory</option>
          </Select>
        </div>

        <Input type="number" min={1} max={32} value={form.max_steps} onChange={(e) => setForm({ ...form, max_steps: Number(e.target.value || 1) })} placeholder="Max Steps" />

        <label className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--text)]">
          <input type="checkbox" checked={form.is_moderator} onChange={(event) => setForm({ ...form, is_moderator: event.target.checked })} />
          <div className="min-w-0">
            <div>将该 Agent 作为 Moderator</div>
            <div className="text-xs text-[var(--muted)]">主持人负责判断讨论是否收敛并决定是否继续下一轮。</div>
          </div>
        </label>

        <label className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--text)]">
          <input type="checkbox" checked={form.is_reporter} onChange={(event) => setForm({ ...form, is_reporter: event.target.checked })} />
          <div className="min-w-0">
            <div>将该 Agent 标记为 Reporter</div>
            <div className="text-xs text-[var(--muted)]">当前后端仍以系统报告生成器为主，但保留 Reporter 配置以保持模型定义完整。</div>
          </div>
        </label>

        <Textarea
          placeholder='Agent extra_config_json，例如：{"style":"strict"}'
          value={form.extra_config_text}
          onChange={(e) => setForm({ ...form, extra_config_text: e.target.value })}
        />

        <div className="space-y-2">
          <p className="text-sm text-[var(--muted)]">可用工具</p>
          <div className="grid gap-2">
            {tools.map((tool) => (
              <label key={tool.id} className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={selectedTools.has(tool.name)}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      tool_names: e.target.checked ? [...form.tool_names, tool.name] : form.tool_names.filter((name) => name !== tool.name),
                    })
                  }
                />
                <div className="min-w-0">
                  <div>{tool.name}</div>
                  <div className="truncate text-xs text-[var(--muted)]">{tool.description}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-sm text-[var(--muted)]">挂载 Skill</p>
          <div className="grid gap-2">
            {skills.map((skill) => (
              <label key={skill.id} className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={selectedSkills.has(skill.id)}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      skill_ids: e.target.checked ? [...form.skill_ids, skill.id] : form.skill_ids.filter((id) => id !== skill.id),
                    })
                  }
                />
                <div className="min-w-0">
                  <div>{skill.name}</div>
                  <div className="truncate text-xs text-[var(--muted)]">{skill.description}</div>
                </div>
              </label>
            ))}
            {!skills.length ? <p className="text-xs text-[var(--muted)]">暂无 Skill，请先到 Skill 管理页面创建。</p> : null}
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-sm text-[var(--muted)]">挂载 MCP</p>
          <div className="grid gap-2">
            {mcps.map((mcp) => (
              <label key={mcp.id} className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={selectedMcps.has(mcp.id)}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      mcp_ids: e.target.checked ? [...form.mcp_ids, mcp.id] : form.mcp_ids.filter((id) => id !== mcp.id),
                    })
                  }
                />
                <div className="min-w-0">
                  <div>{mcp.name}</div>
                  <div className="truncate text-xs text-[var(--muted)]">{mcp.transport_type} · {mcp.description}</div>
                </div>
              </label>
            ))}
            {!mcps.length ? <p className="text-xs text-[var(--muted)]">暂无 MCP，请先到 MCP 管理页面创建。</p> : null}
          </div>
        </div>

        <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--muted)]">
          飞书机器人绑定已迁移到{" "}
          <Link href="/extensions/feishu/bots" className="font-medium text-sky-500 hover:text-sky-400">
            飞书机器人管理页
          </Link>
          ，这里仅展示绑定结果。
        </div>

        {error ? <p className="text-sm text-rose-500">{error}</p> : null}
        <div className="flex flex-wrap gap-3">
          <PrimaryButton type="submit" disabled={loading || !form.name || !form.role || !form.system_prompt || !form.model_id}>
            {loading ? "保存中..." : editing ? "保存修改" : "创建 Agent"}
          </PrimaryButton>
          {editing ? (
            <SecondaryButton type="button" onClick={onReset}>
              取消编辑
            </SecondaryButton>
          ) : null}
        </div>
      </form>
    </Card>
  );
}
