"use client";

import { ProvidersFormCard } from "./providers-form-card";
import { ProvidersListCard } from "./providers-list-card";
import { useProvidersPage } from "./use-providers-page";

export function ProvidersPageClient() {
  const {
    providers,
    providerModelMap,
    providerForm,
    setProviderForm,
    modelForm,
    setModelForm,
    error,
    testing,
    saveProvider,
    saveModel,
    testProvider,
    testModel,
    startEditProvider,
    startEditModel,
    deleteProvider,
    deleteModel,
  } = useProvidersPage();

  return (
    <div className="grid gap-6">
      <ProvidersFormCard
        providerForm={providerForm}
        setProviderForm={setProviderForm}
        modelForm={modelForm}
        setModelForm={setModelForm}
        providers={providers}
        onSaveProvider={saveProvider}
        onSaveModel={saveModel}
      />
      {error ? <p className="text-sm text-rose-500">{error}</p> : null}
      <ProvidersListCard
        groups={providerModelMap}
        testing={testing}
        onEditProvider={startEditProvider}
        onTestProvider={testProvider}
        onDeleteProvider={deleteProvider}
        onEditModel={startEditModel}
        onTestModel={testModel}
        onDeleteModel={deleteModel}
      />
    </div>
  );
}
