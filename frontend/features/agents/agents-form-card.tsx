"use client";

import Link from "next/link";
import { useMemo } from "react";

import { Badge, Card, CheckboxRow, Field, Input, PrimaryButton, SecondaryButton, SectionTitle, Select, Textarea } from "@/components/ui";
import { MCPServerConfig, ModelConfig, SkillConfig, ToolDef } from "@/lib/api";
import { focusField, getJsonObjectError } from "@/lib/form-feedback";

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
  onSubmit: () => Promise<void>;
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
  onSubmit,
  onReset
}: Props) {
  const errors = useMemo(
    () => ({
      name: form.name.trim() ? "" : "请输入 Agent 名称",
      role: form.role.trim() ? "" : "请输入角色定位",
      system_prompt: form.system_prompt.trim() ? "" : "请补充 System Prompt",
      model_id: form.model_id ? "" : "请选择绑定模型",
      max_steps: form.max_steps > 0 ? "" : "Max Steps 必须大于 0",
      extra_config_text: getJsonObjectError(form.extra_config_text, "Agent extra_config_json")
    }),
    [form]
  );

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const firstError = Object.entries(errors).find(([, value]) => value)?.[0];
    if (firstError) {
      focusField(firstError);
      return;
    }
    await onSubmit();
  }

  return (
    <Card className="lg:sticky lg:top-8">
      <SectionTitle
        eyebrow="Agent Builder"
        title={editing ? "编辑 Agent" : "创建 Agent"}
        desc="补全角色定位、主持人属性、工具 / Skill / MCP 组合与额外配置，减少跳转步骤。"
        actions={<Badge tone={form.is_moderator ? "warn" : "default"}>{form.is_moderator ? "Moderator" : "Participant"}</Badge>}
      />
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Agent 名称" required error={errors.name}>
          <Input name="name" placeholder="例如：产品策略主持人" value={form.name} invalid={Boolean(errors.name)} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="角色" required error={errors.role}>
            <Input name="role" placeholder="例如：Moderator / Analyst" value={form.role} invalid={Boolean(errors.role)} onChange={(e) => setForm({ ...form, role: e.target.value })} />
          </Field>
          <Field label="人格 / Persona">
            <Input name="persona" placeholder="例如：冷静、结构化、追求结论" value={form.persona} onChange={(e) => setForm({ ...form, persona: e.target.value })} />
          </Field>
        </div>

        <Field label="System Prompt" required error={errors.system_prompt}>
          <Textarea name="system_prompt" placeholder="定义角色职责、输出风格与决策边界" value={form.system_prompt} invalid={Boolean(errors.system_prompt)} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
        </Field>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="绑定模型" required error={errors.model_id}>
            <Select name="model_id" value={form.model_id} invalid={Boolean(errors.model_id)} onChange={(e) => setForm({ ...form, model_id: e.target.value })}>
              <option value="">选择模型</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.model_name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Memory Strategy">
            <Select name="memory_strategy" value={form.memory_strategy} onChange={(e) => setForm({ ...form, memory_strategy: e.target.value })}>
              <option value="in_memory">in_memory</option>
            </Select>
          </Field>
        </div>

        <Field label="Max Steps" error={errors.max_steps}>
          <Input name="max_steps" type="number" min={1} max={32} value={form.max_steps} invalid={Boolean(errors.max_steps)} onChange={(e) => setForm({ ...form, max_steps: Number(e.target.value || 1) })} />
        </Field>

        <CheckboxRow
          checked={form.is_moderator}
          onChange={(checked) => setForm({ ...form, is_moderator: checked })}
          label="将该 Agent 设为 Moderator"
          description="主持人负责判断讨论是否收敛、沉淀结构化结论，并决定是否继续下一轮。"
          badge={<Badge tone={form.is_moderator ? "warn" : "default"}>{form.is_moderator ? "主持中枢" : "普通参与者"}</Badge>}
        />

        <Field label="扩展 JSON" hint="必须是 JSON 对象" error={errors.extra_config_text}>
          <Textarea
            name="extra_config_text"
            placeholder='例如：{"style":"strict","temperature_cap":0.5}'
            value={form.extra_config_text}
            invalid={Boolean(errors.extra_config_text)}
            onChange={(e) => setForm({ ...form, extra_config_text: e.target.value })}
          />
        </Field>

        <div className="space-y-3 rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
          <div>
            <div className="text-sm font-medium text-[var(--text)]">可用工具</div>
            <div className="mt-1 text-sm text-[var(--muted)]">勾选后会直接注入到该 Agent 的工具能力集中。</div>
          </div>
          <div className="grid gap-2">
            {tools.map((tool) => (
              <CheckboxRow
                key={tool.id}
                checked={selectedTools.has(tool.name)}
                onChange={(checked) =>
                  setForm({
                    ...form,
                    tool_names: checked ? [...form.tool_names, tool.name] : form.tool_names.filter((name) => name !== tool.name)
                  })
                }
                label={tool.name}
                description={tool.description}
              />
            ))}
          </div>
        </div>

        <div className="space-y-3 rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
          <div>
            <div className="text-sm font-medium text-[var(--text)]">挂载 Skill</div>
            <div className="mt-1 text-sm text-[var(--muted)]">把领域知识和提示模板沉淀到角色能力中。</div>
          </div>
          <div className="grid gap-2">
            {skills.map((skill) => (
              <CheckboxRow
                key={skill.id}
                checked={selectedSkills.has(skill.id)}
                onChange={(checked) =>
                  setForm({
                    ...form,
                    skill_ids: checked ? [...form.skill_ids, skill.id] : form.skill_ids.filter((id) => id !== skill.id)
                  })
                }
                label={skill.name}
                description={skill.description}
                badge={<Badge tone={skill.enabled ? "success" : "warn"}>{skill.enabled ? "enabled" : "disabled"}</Badge>}
              />
            ))}
            {!skills.length ? <p className="text-sm text-[var(--muted)]">当前还没有 Skill，可先前往 Skill 管理页面创建。</p> : null}
          </div>
        </div>

        <div className="space-y-3 rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4">
          <div>
            <div className="text-sm font-medium text-[var(--text)]">挂载 MCP</div>
            <div className="mt-1 text-sm text-[var(--muted)]">用于接入外部工具链或业务系统能力。</div>
          </div>
          <div className="grid gap-2">
            {mcps.map((mcp) => (
              <CheckboxRow
                key={mcp.id}
                checked={selectedMcps.has(mcp.id)}
                onChange={(checked) =>
                  setForm({
                    ...form,
                    mcp_ids: checked ? [...form.mcp_ids, mcp.id] : form.mcp_ids.filter((id) => id !== mcp.id)
                  })
                }
                label={mcp.name}
                description={`${mcp.transport_type} · ${mcp.description}`}
                badge={<Badge tone={mcp.enabled ? "success" : "warn"}>{mcp.enabled ? "enabled" : "disabled"}</Badge>}
              />
            ))}
            {!mcps.length ? <p className="text-sm text-[var(--muted)]">当前还没有 MCP，可先前往 MCP 管理页面创建。</p> : null}
          </div>
        </div>

        <div className="rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-4 text-sm leading-7 text-[var(--muted)]">
          飞书机器人绑定已迁移到
          <Link href="/extensions/feishu/bots" className="mx-1 font-medium text-[var(--brand-strong)] hover:opacity-80">
            飞书机器人管理
          </Link>
          页面，这里专注角色编排与能力装配。
        </div>

        <div className="flex flex-wrap gap-3">
          <PrimaryButton type="submit" loading={loading}>
            {editing ? "保存 Agent" : "创建 Agent"}
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
