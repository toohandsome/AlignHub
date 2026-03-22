"use client";

import { Badge, Card, InlineAlert, SectionTitle, Skeleton } from "@/components/ui";

import { AgentsFormCard } from "./agents-form-card";
import { AgentsListCard } from "./agents-list-card";
import { useAgentsPage } from "./use-agents-page";

export function AgentsPageClient() {
  const {
    agents,
    models,
    tools,
    skills,
    mcps,
    form,
    setForm,
    loading,
    error,
    bootstrapping,
    busyAgentId,
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
    startEdit
  } = useAgentsPage();

  if (bootstrapping) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1.18fr_0.96fr]">
        <Skeleton className="h-[840px]" />
        <Skeleton className="h-[920px]" />
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="Role Design" title="Agent 角色编排台" desc="把模型、工具、Skill、MCP 和主持人职责统一装配到角色层，缩短会话准备时间。" />
        <div className="flex flex-wrap gap-2">
          <Badge>{agents.length} 个 Agent</Badge>
          <Badge tone="success">{models.length} 个可用模型</Badge>
          <Badge tone="warn">{agents.filter((item) => item.is_moderator).length} 个 Moderator</Badge>
        </div>
      </Card>

      {error ? <InlineAlert tone="danger" title="Agent 页面操作失败" description={error} /> : null}

      <div className="grid gap-6 lg:grid-cols-[1.18fr_0.96fr]">
        <AgentsListCard agents={agents} busyAgentId={busyAgentId} agentDirectory={agentDirectory} modelMap={modelMap} onEdit={startEdit} onCopy={copyAgent} onDelete={removeAgent} />
        <AgentsFormCard
          editing={editing}
          form={form}
          setForm={setForm}
          models={models}
          tools={tools}
          skills={skills}
          mcps={mcps}
          selectedTools={selectedTools}
          selectedSkills={selectedSkills}
          selectedMcps={selectedMcps}
          loading={loading}
          onSubmit={onSubmit}
          onReset={resetForm}
        />
      </div>
    </div>
  );
}
