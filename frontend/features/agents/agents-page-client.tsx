"use client";

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
  } = useAgentsPage();

  return (
    <div className="grid gap-6 lg:grid-cols-[1.2fr_0.95fr]">
      <AgentsListCard agents={agents} agentDirectory={agentDirectory} modelMap={modelMap} onEdit={startEdit} onCopy={copyAgent} onDelete={removeAgent} />
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
        error={error}
        onSubmit={onSubmit}
        onReset={resetForm}
      />
    </div>
  );
}
