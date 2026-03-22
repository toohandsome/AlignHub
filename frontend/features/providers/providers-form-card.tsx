"use client";

import { useMemo } from "react";

import { Badge, Card, CheckboxRow, Field, PrimaryButton, SecondaryButton, SectionTitle, Select, Textarea, Input } from "@/components/ui";
import { focusField, getJsonObjectError } from "@/lib/form-feedback";
import { Provider } from "@/lib/api";

import { ModelForm, ProviderForm, emptyModel, emptyProvider } from "./use-providers-page";

type Props = {
  providerForm: ProviderForm;
  setProviderForm: (value: ProviderForm) => void;
  modelForm: ModelForm;
  setModelForm: (value: ModelForm) => void;
  providers: Provider[];
  providerSubmitting: boolean;
  modelSubmitting: boolean;
  onSaveProvider: () => Promise<void>;
  onSaveModel: () => Promise<void>;
};

export function ProvidersFormCard({
  providerForm,
  setProviderForm,
  modelForm,
  setModelForm,
  providers,
  providerSubmitting,
  modelSubmitting,
  onSaveProvider,
  onSaveModel
}: Props) {
  const providerErrors = useMemo(
    () => ({
      name: providerForm.name.trim() ? "" : "请输入 Provider 名称",
      extra_config_text: getJsonObjectError(providerForm.extra_config_text, "Provider extra_config_json")
    }),
    [providerForm]
  );

  const modelErrors = useMemo(() => {
    const topP = modelForm.top_p.trim();
    const parsedTopP = topP ? Number(topP) : Number.NaN;
    const invalidTopP = Boolean(topP) && (!Number.isFinite(parsedTopP) || parsedTopP < 0 || parsedTopP > 1);

    return {
      provider_id: modelForm.provider_id ? "" : "请先选择所属 Provider",
      model_name: modelForm.model_name.trim() ? "" : "请输入 Model 名称",
      temperature: Number.isFinite(modelForm.temperature) ? "" : "Temperature 需要是数字",
      max_tokens: modelForm.max_tokens > 0 ? "" : "Max Tokens 必须大于 0",
      top_p: invalidTopP ? "Top P 需位于 0 到 1 之间" : "",
      extra_config_text: getJsonObjectError(modelForm.extra_config_text, "Model extra_config_json")
    };
  }, [modelForm]);

  async function handleProviderSubmit(event: React.FormEvent) {
    event.preventDefault();
    const firstError = Object.entries(providerErrors).find(([, value]) => value)?.[0];
    if (firstError) {
      focusField(firstError);
      return;
    }
    await onSaveProvider();
  }

  async function handleModelSubmit(event: React.FormEvent) {
    event.preventDefault();
    const firstError = Object.entries(modelErrors).find(([, value]) => value)?.[0];
    if (firstError) {
      focusField(firstError);
      return;
    }
    await onSaveModel();
  }

  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-2">
      <Card>
        <SectionTitle
          eyebrow="Provider"
          title={providerForm.id ? "编辑 Provider" : "创建 Provider"}
          desc="统一维护模型供应商、连接地址与 Provider 级扩展配置。保留 API Key 为空时，编辑不会覆盖原值。"
          actions={<Badge>{providerForm.id ? "Editing" : "New"}</Badge>}
        />
        <form onSubmit={handleProviderSubmit} className="space-y-4">
          <Field label="Provider 类型" required>
            <Select name="provider_type" value={providerForm.provider_type} onChange={(e) => setProviderForm({ ...providerForm, provider_type: e.target.value })}>
              {["mock", "openai", "azure", "openrouter", "openai_compatible", "anthropic", "ollama"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Provider 名称" required error={providerErrors.name}>
            <Input name="name" placeholder="例如：OpenAI Production" value={providerForm.name} invalid={Boolean(providerErrors.name)} onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })} />
          </Field>

          <Field label="API Key" hint={providerForm.id ? "留空表示不修改" : "可稍后补充"}>
            <Input name="api_key" type="password" placeholder="sk-..." value={providerForm.api_key} onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })} />
          </Field>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Base URL">
              <Input name="base_url" placeholder="https://api.example.com" value={providerForm.base_url} onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })} />
            </Field>
            <Field label="Organization">
              <Input name="organization" placeholder="org_xxx" value={providerForm.organization} onChange={(e) => setProviderForm({ ...providerForm, organization: e.target.value })} />
            </Field>
          </div>

          <Field label="扩展 JSON" hint="必须是 JSON 对象" error={providerErrors.extra_config_text}>
            <Textarea
              name="extra_config_text"
              invalid={Boolean(providerErrors.extra_config_text)}
              placeholder='例如：{"timeout":30,"region":"global"}'
              value={providerForm.extra_config_text}
              onChange={(e) => setProviderForm({ ...providerForm, extra_config_text: e.target.value })}
            />
          </Field>

          <div className="flex flex-wrap gap-3">
            <PrimaryButton type="submit" loading={providerSubmitting}>
              {providerForm.id ? "保存 Provider" : "创建 Provider"}
            </PrimaryButton>
            {providerForm.id ? (
              <SecondaryButton type="button" onClick={() => setProviderForm({ ...emptyProvider, provider_type: providerForm.provider_type })}>
                取消编辑
              </SecondaryButton>
            ) : null}
          </div>
        </form>
      </Card>

      <Card>
        <SectionTitle
          eyebrow="Model"
          title={modelForm.id ? "编辑 Model" : "创建 Model"}
          desc="补全 temperature、max_tokens、stream、formatter 等模型参数，创建后即可绑定到 Agent。"
          actions={<Badge tone="success">{providers.length} 个 Provider 可选</Badge>}
        />
        <form onSubmit={handleModelSubmit} className="space-y-4">
          <Field label="所属 Provider" required error={modelErrors.provider_id}>
            <Select name="provider_id" value={modelForm.provider_id} invalid={Boolean(modelErrors.provider_id)} onChange={(e) => setModelForm({ ...modelForm, provider_id: e.target.value })}>
              <option value="">选择 Provider</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Model 名称" required error={modelErrors.model_name}>
            <Input name="model_name" placeholder="例如：gpt-4.1" value={modelForm.model_name} invalid={Boolean(modelErrors.model_name)} onChange={(e) => setModelForm({ ...modelForm, model_name: e.target.value })} />
          </Field>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Temperature" error={modelErrors.temperature}>
              <Input
                name="temperature"
                type="number"
                step="0.1"
                value={modelForm.temperature}
                invalid={Boolean(modelErrors.temperature)}
                onChange={(e) => setModelForm({ ...modelForm, temperature: Number(e.target.value) })}
              />
            </Field>
            <Field label="Max Tokens" error={modelErrors.max_tokens}>
              <Input
                name="max_tokens"
                type="number"
                min={1}
                value={modelForm.max_tokens}
                invalid={Boolean(modelErrors.max_tokens)}
                onChange={(e) => setModelForm({ ...modelForm, max_tokens: Number(e.target.value || 1) })}
              />
            </Field>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Top P" hint="可留空" error={modelErrors.top_p}>
              <Input name="top_p" placeholder="0 ~ 1" value={modelForm.top_p} invalid={Boolean(modelErrors.top_p)} onChange={(e) => setModelForm({ ...modelForm, top_p: e.target.value })} />
            </Field>
            <Field label="Formatter Type">
              <Input name="formatter_type" placeholder="auto" value={modelForm.formatter_type} onChange={(e) => setModelForm({ ...modelForm, formatter_type: e.target.value })} />
            </Field>
          </div>

          <CheckboxRow
            checked={modelForm.stream_enabled}
            onChange={(checked) => setModelForm({ ...modelForm, stream_enabled: checked })}
            label="启用流式输出"
            description="适合对话生成、事件流渲染等需要边生成边展示的场景。"
            badge={<Badge tone={modelForm.stream_enabled ? "success" : "default"}>{modelForm.stream_enabled ? "stream=true" : "stream=false"}</Badge>}
          />

          <Field label="扩展 JSON" hint="必须是 JSON 对象" error={modelErrors.extra_config_text}>
            <Textarea
              name="extra_config_text"
              invalid={Boolean(modelErrors.extra_config_text)}
              placeholder='例如：{"client_kwargs":{"timeout":30}}'
              value={modelForm.extra_config_text}
              onChange={(e) => setModelForm({ ...modelForm, extra_config_text: e.target.value })}
            />
          </Field>

          <div className="flex flex-wrap gap-3">
            <PrimaryButton type="submit" loading={modelSubmitting}>
              {modelForm.id ? "保存 Model" : "创建 Model"}
            </PrimaryButton>
            {modelForm.id ? (
              <SecondaryButton type="button" onClick={() => setModelForm({ ...emptyModel, provider_id: providers[0]?.id || "" })}>
                取消编辑
              </SecondaryButton>
            ) : null}
          </div>
        </form>
      </Card>
    </div>
  );
}

