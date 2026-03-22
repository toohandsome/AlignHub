"use client";

import { Badge, Card, EmptyState, PrimaryButton, SecondaryButton, SectionTitle } from "@/components/ui";
import { ConnectionTestResult, ModelConfig, Provider } from "@/lib/api";

type ProviderModelGroup = {
  provider: Provider;
  models: ModelConfig[];
};

function ResultBadge({ result }: { result?: ConnectionTestResult }) {
  if (!result) return <Badge>未测试</Badge>;
  return <Badge tone={result.success ? "success" : "danger"}>{result.success ? "连接成功" : "连接失败"}</Badge>;
}

type Props = {
  groups: ProviderModelGroup[];
  testing: Record<string, ConnectionTestResult>;
  testingId: string | null;
  removingId: string | null;
  onEditProvider: (provider: Provider) => void;
  onTestProvider: (providerId: string) => Promise<void>;
  onDeleteProvider: (providerId: string) => Promise<void>;
  onEditModel: (model: ModelConfig) => void;
  onTestModel: (modelId: string) => Promise<void>;
  onDeleteModel: (modelId: string) => Promise<void>;
};

export function ProvidersListCard({
  groups,
  testing,
  testingId,
  removingId,
  onEditProvider,
  onTestProvider,
  onDeleteProvider,
  onEditModel,
  onTestModel,
  onDeleteModel
}: Props) {
  return (
    <Card>
      <SectionTitle eyebrow="Inventory" title="Provider / Model 列表" desc="按 Provider 聚合查看模型配置、扩展参数与最近一次测试结果。" />
      <div className="grid gap-4">
        {groups.map(({ provider, models: providerModels }) => (
          <div key={provider.id} className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-semibold text-[var(--text)]">{provider.name}</h3>
                  <Badge>{provider.provider_type}</Badge>
                  <ResultBadge result={testing[provider.id]} />
                </div>
                <div className="mt-3 grid gap-1 text-sm text-[var(--muted)]">
                  <div>Base URL：{provider.base_url || "-"}</div>
                  <div>API Key：{provider.api_key_masked || "-"}</div>
                  <div>模型数量：{providerModels.length}</div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <PrimaryButton type="button" onClick={() => onEditProvider(provider)}>
                  编辑
                </PrimaryButton>
                <SecondaryButton type="button" loading={testingId === provider.id} onClick={() => void onTestProvider(provider.id)}>
                  测试 Provider
                </SecondaryButton>
                <SecondaryButton
                  type="button"
                  loading={removingId === provider.id}
                  onClick={() => {
                    if (!window.confirm(`确认删除 Provider “${provider.name}” 吗？`)) return;
                    void onDeleteProvider(provider.id);
                  }}
                >
                  删除
                </SecondaryButton>
              </div>
            </div>

            {provider.extra_config_json ? <pre className="mt-4 overflow-x-auto rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(provider.extra_config_json, null, 2)}</pre> : null}
            {testing[provider.id] ? <pre className="mt-3 overflow-x-auto rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(testing[provider.id], null, 2)}</pre> : null}

            <div className="mt-5 grid gap-3">
              {providerModels.length ? (
                providerModels.map((model) => (
                  <div key={model.id} className="rounded-[24px] border border-[var(--line)] bg-[var(--panel)] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="text-base font-medium text-[var(--text)]">{model.model_name}</div>
                          <ResultBadge result={testing[model.id]} />
                          <Badge tone={model.stream_enabled ? "success" : "default"}>{model.stream_enabled ? "stream" : "non-stream"}</Badge>
                        </div>
                        <div className="mt-2 text-sm text-[var(--muted)]">
                          temperature={model.temperature} · max_tokens={model.max_tokens} · top_p={model.top_p ?? "-"} · formatter={model.formatter_type || "auto"}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <PrimaryButton type="button" onClick={() => onEditModel(model)}>
                          编辑
                        </PrimaryButton>
                        <SecondaryButton type="button" loading={testingId === model.id} onClick={() => void onTestModel(model.id)}>
                          测试 Model
                        </SecondaryButton>
                        <SecondaryButton
                          type="button"
                          loading={removingId === model.id}
                          onClick={() => {
                            if (!window.confirm(`确认删除 Model “${model.model_name}” 吗？`)) return;
                            void onDeleteModel(model.id);
                          }}
                        >
                          删除
                        </SecondaryButton>
                      </div>
                    </div>
                    <pre className="mt-3 overflow-x-auto rounded-2xl bg-[var(--panel-2)] p-3 text-xs text-[var(--muted)]">{JSON.stringify({ extra_config_json: model.extra_config_json ?? {} }, null, 2)}</pre>
                    {testing[model.id] ? <pre className="mt-3 overflow-x-auto rounded-2xl bg-[var(--panel-2)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(testing[model.id], null, 2)}</pre> : null}
                  </div>
                ))
              ) : (
                <EmptyState title="该 Provider 还没有 Model" description="可以直接在上方创建新 Model，保存后会自动归类到当前 Provider 下。" />
              )}
            </div>
          </div>
        ))}

        {!groups.length ? <EmptyState title="还没有任何 Provider" description="建议先创建一个 Provider，再继续补充 Model 与 Agent 绑定。" /> : null}
      </div>
    </Card>
  );
}
