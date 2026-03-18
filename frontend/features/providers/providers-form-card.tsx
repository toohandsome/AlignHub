"use client";

import { type FormEvent } from "react";

import { Badge, Card, Input, PrimaryButton, SecondaryButton, SectionTitle, Select, Textarea } from "@/components/ui";
import { Provider } from "@/lib/api";

import { ModelForm, ProviderForm } from "./use-providers-page";

type Props = {
  providerForm: ProviderForm;
  setProviderForm: (value: ProviderForm) => void;
  modelForm: ModelForm;
  setModelForm: (value: ModelForm) => void;
  providers: Provider[];
  onSaveProvider: (event: FormEvent) => Promise<void>;
  onSaveModel: (event: FormEvent) => Promise<void>;
};

export function ProvidersFormCard({
  providerForm,
  setProviderForm,
  modelForm,
  setModelForm,
  providers,
  onSaveProvider,
  onSaveModel,
}: Props) {
  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-2">
      <Card>
        <SectionTitle title={providerForm.id ? "编辑 Provider" : "创建 Provider"} desc="补全 Provider 级额外配置，空 API Key 表示更新时保持不变。" />
        <form onSubmit={onSaveProvider} className="space-y-3">
          <Select value={providerForm.provider_type} onChange={(e) => setProviderForm({ ...providerForm, provider_type: e.target.value })}>
            {["mock", "openai", "azure", "openrouter", "openai_compatible", "anthropic", "ollama"].map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
          <Input placeholder="Provider 名称" value={providerForm.name} onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })} />
          <Input placeholder="API Key（编辑时留空表示不修改）" value={providerForm.api_key} onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })} />
          <Input placeholder="Base URL" value={providerForm.base_url} onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })} />
          <Input placeholder="Organization" value={providerForm.organization} onChange={(e) => setProviderForm({ ...providerForm, organization: e.target.value })} />
          <Textarea
            placeholder='Provider extra_config_json，例如：{"timeout":30}'
            value={providerForm.extra_config_text}
            onChange={(e) => setProviderForm({ ...providerForm, extra_config_text: e.target.value })}
          />
          <div className="flex gap-3">
            <PrimaryButton type="submit">{providerForm.id ? "保存 Provider" : "创建 Provider"}</PrimaryButton>
            {providerForm.id ? (
              <SecondaryButton type="button" onClick={() => setProviderForm({ provider_type: providerForm.provider_type, name: "", api_key: "", base_url: "", organization: "", extra_config_text: "{}" })}>
                取消
              </SecondaryButton>
            ) : null}
          </div>
        </form>
      </Card>

      <Card>
        <SectionTitle title={modelForm.id ? "编辑 Model" : "创建 Model"} desc="补全 top_p / stream_enabled / extra_config_json 等配置项。" />
        <form onSubmit={onSaveModel} className="space-y-3">
          <Select value={modelForm.provider_id} onChange={(e) => setModelForm({ ...modelForm, provider_id: e.target.value })}>
            <option value="">选择 Provider</option>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name}
              </option>
            ))}
          </Select>
          <Input placeholder="Model 名称" value={modelForm.model_name} onChange={(e) => setModelForm({ ...modelForm, model_name: e.target.value })} />
          <div className="grid gap-3 md:grid-cols-2">
            <Input type="number" step="0.1" value={modelForm.temperature} onChange={(e) => setModelForm({ ...modelForm, temperature: Number(e.target.value) })} placeholder="Temperature" />
            <Input type="number" value={modelForm.max_tokens} onChange={(e) => setModelForm({ ...modelForm, max_tokens: Number(e.target.value) })} placeholder="Max Tokens" />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <Input placeholder="Top P（可留空）" value={modelForm.top_p} onChange={(e) => setModelForm({ ...modelForm, top_p: e.target.value })} />
            <Input placeholder="Formatter Type" value={modelForm.formatter_type} onChange={(e) => setModelForm({ ...modelForm, formatter_type: e.target.value })} />
          </div>
          <label className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--text)]">
            <input type="checkbox" checked={modelForm.stream_enabled} onChange={(e) => setModelForm({ ...modelForm, stream_enabled: e.target.checked })} />
            <span>启用流式输出</span>
            <Badge tone={modelForm.stream_enabled ? "success" : "default"}>{modelForm.stream_enabled ? "stream=true" : "stream=false"}</Badge>
          </label>
          <Textarea
            placeholder='Model extra_config_json，例如：{"client_kwargs":{"timeout":30}}'
            value={modelForm.extra_config_text}
            onChange={(e) => setModelForm({ ...modelForm, extra_config_text: e.target.value })}
          />
          <div className="flex gap-3">
            <PrimaryButton type="submit">{modelForm.id ? "保存 Model" : "创建 Model"}</PrimaryButton>
            {modelForm.id ? (
              <SecondaryButton type="button" onClick={() => setModelForm({ provider_id: providers[0]?.id || "", model_name: "", temperature: 0.7, max_tokens: 1024, top_p: "", stream_enabled: false, formatter_type: "auto", extra_config_text: "{}" })}>
                取消
              </SecondaryButton>
            ) : null}
          </div>
        </form>
      </Card>
    </div>
  );
}
