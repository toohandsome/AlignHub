"use client";

import { Badge, Card, InlineAlert, SectionTitle, Skeleton } from "@/components/ui";

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
    bootstrapping,
    submitting,
    testingId,
    removingId,
    saveProvider,
    saveModel,
    testProvider,
    testModel,
    startEditProvider,
    startEditModel,
    deleteProvider,
    deleteModel
  } = useProvidersPage();

  if (bootstrapping) {
    return (
      <div className="grid gap-6">
        <div className="grid gap-6 xl:grid-cols-2">
          <Skeleton className="h-[540px]" />
          <Skeleton className="h-[540px]" />
        </div>
        <Skeleton className="h-[520px]" />
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="Model Foundation" title="Provider / Model 工作台" desc="统一完成供应商接入、模型参数维护与连通性验证，减少配置切换。" />
        <div className="flex flex-wrap gap-2">
          <Badge>{providers.length} 个 Provider</Badge>
          <Badge tone="success">{providerModelMap.reduce((sum, item) => sum + item.models.length, 0)} 个 Model</Badge>
          <Badge tone="warn">支持实时连接测试</Badge>
        </div>
      </Card>

      {error ? <InlineAlert tone="danger" title="加载或操作时出现问题" description={error} /> : null}

      <ProvidersFormCard
        providerForm={providerForm}
        setProviderForm={setProviderForm}
        modelForm={modelForm}
        setModelForm={setModelForm}
        providers={providers}
        providerSubmitting={submitting === "provider"}
        modelSubmitting={submitting === "model"}
        onSaveProvider={saveProvider}
        onSaveModel={saveModel}
      />
      <ProvidersListCard
        groups={providerModelMap}
        testing={testing}
        testingId={testingId}
        removingId={removingId}
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
