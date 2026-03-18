"use client";

import { Badge, Card, PrimaryButton, SecondaryButton, SectionTitle } from "@/components/ui";
import { ConnectionTestResult, ModelConfig, Provider } from "@/lib/api";

type ProviderModelGroup = {
  provider: Provider;
  models: ModelConfig[];
};

function ResultBadge({ result }: { result?: ConnectionTestResult }) {
  if (!result) return null;
  return <Badge tone={result.success ? "success" : "danger"}>{result.success ? "连接成功" : "连接失败"}</Badge>;
}

type Props = {
  groups: ProviderModelGroup[];
  testing: Record<string, ConnectionTestResult>;
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
  onEditProvider,
  onTestProvider,
  onDeleteProvider,
  onEditModel,
  onTestModel,
  onDeleteModel,
}: Props) {
  return (
    <Card>
      <SectionTitle title="Provider / Model 列表" desc="展示完整模型配置，包括 top_p / stream / formatter / extra_config_json。" />
      <div className="grid gap-4">
        {groups.map(({ provider, models: providerModels }) => (
          <div key={provider.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-medium text-[var(--text)]">{provider.name}</h3>
                  <Badge>{provider.provider_type}</Badge>
                  <ResultBadge result={testing[provider.id]} />
                </div>
                <p className="mt-1 text-xs text-[var(--muted)]">Base URL: {provider.base_url || "-"}</p>
                <p className="mt-1 text-xs text-[var(--muted)]">API Key: {provider.api_key_masked || "-"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <PrimaryButton type="button" onClick={() => onEditProvider(provider)}>
                  编辑
                </PrimaryButton>
                <SecondaryButton type="button" onClick={() => void onTestProvider(provider.id)}>
                  测试 Provider
                </SecondaryButton>
                <SecondaryButton
                  type="button"
                  onClick={() => {
                    if (!window.confirm("确认删除这个 Provider 吗？")) return;
                    void onDeleteProvider(provider.id);
                  }}
                >
                  删除
                </SecondaryButton>
              </div>
            </div>

            {provider.extra_config_json ? (
              <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(provider.extra_config_json, null, 2)}</pre>
            ) : null}
            {testing[provider.id] ? <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(testing[provider.id], null, 2)}</pre> : null}

            <div className="mt-4 grid gap-3">
              {providerModels.map((model) => (
                <div key={model.id} className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <div className="font-medium text-[var(--text)]">{model.model_name}</div>
                        <ResultBadge result={testing[model.id]} />
                        <Badge tone={model.stream_enabled ? "success" : "default"}>{model.stream_enabled ? "stream" : "non-stream"}</Badge>
                      </div>
                      <div className="text-xs text-[var(--muted)]">
                        temp={model.temperature} · max_tokens={model.max_tokens} · top_p={model.top_p ?? "-"} · formatter={model.formatter_type}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <PrimaryButton type="button" onClick={() => onEditModel(model)}>
                        编辑
                      </PrimaryButton>
                      <SecondaryButton type="button" onClick={() => void onTestModel(model.id)}>
                        测试 Model
                      </SecondaryButton>
                      <SecondaryButton
                        type="button"
                        onClick={() => {
                          if (!window.confirm("确认删除这个 Model 吗？")) return;
                          void onDeleteModel(model.id);
                        }}
                      >
                        删除
                      </SecondaryButton>
                    </div>
                  </div>
                  <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel-2)] p-3 text-xs text-[var(--muted)]">
                    {JSON.stringify(
                      {
                        extra_config_json: model.extra_config_json ?? {},
                      },
                      null,
                      2
                    )}
                  </pre>
                  {testing[model.id] ? <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel-2)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(testing[model.id], null, 2)}</pre> : null}
                </div>
              ))}
              {!providerModels.length ? <p className="text-sm text-[var(--muted)]">该 Provider 暂无 Model。</p> : null}
            </div>
          </div>
        ))}
        {!groups.length ? <p className="text-sm text-[var(--muted)]">暂无 Provider，请先创建。</p> : null}
      </div>
    </Card>
  );
}
