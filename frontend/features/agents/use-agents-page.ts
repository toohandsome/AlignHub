"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import { AgentConfig, api, MCPServerConfig, ModelConfig, SkillConfig, ToolDef } from "@/lib/api";
import { prettyJson, parseJsonObjectText } from "@/lib/json-form";
import { buildAgentDirectory } from "@/lib/discussion";

export type AgentForm = {
  id?: string;
  name: string;
  role: string;
  persona: string;
  system_prompt: string;
  model_id: string;
  memory_strategy: string;
  max_steps: number;
  is_moderator: boolean;
  is_reporter: boolean;
  tool_names: string[];
  skill_ids: string[];
  mcp_ids: string[];
  extra_config_text: string;
};

export const emptyAgentForm: AgentForm = {
  name: "",
  role: "",
  persona: "",
  system_prompt: "",
  model_id: "",
  memory_strategy: "in_memory",
  max_steps: 6,
  is_moderator: false,
  is_reporter: false,
  tool_names: [],
  skill_ids: [],
  mcp_ids: [],
  extra_config_text: "{}",
};

export function useAgentsPage() {
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [tools, setTools] = useState<ToolDef[]>([]);
  const [skills, setSkills] = useState<SkillConfig[]>([]);
  const [mcps, setMcps] = useState<MCPServerConfig[]>([]);
  const [form, setForm] = useState<AgentForm>(emptyAgentForm);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  async function loadAll() {
    const [agentData, modelData, toolData, skillData, mcpData] = await Promise.all([
      api.get<AgentConfig[]>("/agents"),
      api.get<ModelConfig[]>("/models"),
      api.get<ToolDef[]>("/tools"),
      api.get<SkillConfig[]>("/skills"),
      api.get<MCPServerConfig[]>("/mcps"),
    ]);
    setAgents(agentData);
    setModels(modelData);
    setTools(toolData);
    setSkills(skillData);
    setMcps(mcpData);
    setForm((prev) => ({ ...prev, model_id: prev.model_id || modelData[0]?.id || "" }));
  }

  useEffect(() => {
    loadAll().catch((err) => setError(err.message));
  }, []);

  const selectedTools = useMemo(() => new Set(form.tool_names), [form.tool_names]);
  const selectedSkills = useMemo(() => new Set(form.skill_ids), [form.skill_ids]);
  const selectedMcps = useMemo(() => new Set(form.mcp_ids), [form.mcp_ids]);
  const editing = Boolean(form.id);
  const agentDirectory = useMemo(() => buildAgentDirectory(agents, models), [agents, models]);
  const modelMap = useMemo(() => Object.fromEntries(models.map((model) => [model.id, model])), [models]);

  function resetForm() {
    setForm({ ...emptyAgentForm, model_id: models[0]?.id || "" });
    setError("");
  }

  function buildCopyName(baseName: string) {
    const existing = new Set(agents.map((item) => item.name));
    let candidate = `${baseName} Copy`;
    let index = 2;
    while (existing.has(candidate)) {
      candidate = `${baseName} Copy ${index}`;
      index += 1;
    }
    return candidate;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = {
        name: form.name,
        role: form.role,
        persona: form.persona,
        system_prompt: form.system_prompt,
        model_id: form.model_id,
        memory_strategy: form.memory_strategy,
        max_steps: form.max_steps,
        is_moderator: form.is_moderator,
        is_reporter: form.is_reporter,
        tool_names: form.tool_names,
        skill_ids: form.skill_ids,
        mcp_ids: form.mcp_ids,
        extra_config_json: parseJsonObjectText(form.extra_config_text, "Agent extra_config_json"),
      };
      if (form.id) {
        await api.put<AgentConfig>(`/agents/${form.id}`, payload);
      } else {
        await api.post<AgentConfig>("/agents", payload);
      }
      resetForm();
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setLoading(false);
    }
  }

  async function removeAgent(agentId: string) {
    await api.del(`/agents/${agentId}`);
    if (form.id === agentId) resetForm();
    await loadAll();
  }

  async function copyAgent(agent: AgentConfig) {
    try {
      setError("");
      await api.post("/agents", {
        name: buildCopyName(agent.name),
        role: agent.role,
        persona: agent.persona ?? "",
        system_prompt: agent.system_prompt,
        model_id: agent.model_id,
        memory_strategy: agent.memory_strategy,
        max_steps: agent.max_steps,
        is_moderator: Boolean(agent.is_moderator),
        is_reporter: Boolean(agent.is_reporter),
        tool_names: [...agent.tool_names],
        skill_ids: [...agent.skill_ids],
        mcp_ids: [...agent.mcp_ids],
        extra_config_json: agent.extra_config_json ?? {},
      });
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制 Agent 失败");
    }
  }

  function startEdit(agent: AgentConfig) {
    setForm({
      id: agent.id,
      name: agent.name,
      role: agent.role,
      persona: agent.persona ?? "",
      system_prompt: agent.system_prompt,
      model_id: agent.model_id,
      memory_strategy: agent.memory_strategy,
      max_steps: agent.max_steps,
      is_moderator: Boolean(agent.is_moderator),
      is_reporter: Boolean(agent.is_reporter),
      tool_names: [...agent.tool_names],
      skill_ids: [...agent.skill_ids],
      mcp_ids: [...agent.mcp_ids],
      extra_config_text: prettyJson(agent.extra_config_json ?? {}),
    });
    setError("");
  }

  return {
    agents,
    models,
    tools,
    skills,
    mcps,
    form,
    setForm,
    loading,
    error,
    setError,
    selectedTools,
    selectedSkills,
    selectedMcps,
    editing,
    agentDirectory,
    modelMap,
    resetForm,
    onSubmit,
    removeAgent,
    copyAgent,
    startEdit,
    reload: loadAll,
  };
}
