"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";

import { api, ConnectionTestResult, ModelConfig, Provider } from "@/lib/api";
import { parseJsonObjectText, prettyJson } from "@/lib/json-form";

export type ProviderForm = {
  id?: string;
  provider_type: string;
  name: string;
  api_key: string;
  base_url: string;
  organization: string;
  extra_config_text: string;
};

export type ModelForm = {
  id?: string;
  provider_id: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  top_p: string;
  stream_enabled: boolean;
  formatter_type: string;
  extra_config_text: string;
};

export const emptyProvider: ProviderForm = {
  provider_type: "mock",
  name: "",
  api_key: "",
  base_url: "",
  organization: "",
  extra_config_text: "{}",
};

export const emptyModel: ModelForm = {
  provider_id: "",
  model_name: "",
  temperature: 0.7,
  max_tokens: 1024,
  top_p: "",
  stream_enabled: false,
  formatter_type: "auto",
  extra_config_text: "{}",
};

export function useProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [providerForm, setProviderForm] = useState<ProviderForm>(emptyProvider);
  const [modelForm, setModelForm] = useState<ModelForm>(emptyModel);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState<Record<string, ConnectionTestResult>>({});

  async function loadAll() {
    const [providerData, modelData] = await Promise.all([api.get<Provider[]>("/providers"), api.get<ModelConfig[]>("/models")]);
    setProviders(providerData);
    setModels(modelData);
    setModelForm((prev) => ({ ...prev, provider_id: prev.provider_id || providerData[0]?.id || "" }));
  }

  useEffect(() => {
    loadAll().catch((err) => setError(err.message));
  }, []);

  const providerModelMap = useMemo(
    () => providers.map((provider) => ({ provider, models: models.filter((model) => model.provider_id === provider.id) })),
    [providers, models]
  );

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const payload: Record<string, unknown> = {
        provider_type: providerForm.provider_type,
        name: providerForm.name,
        base_url: providerForm.base_url || null,
        organization: providerForm.organization || null,
        extra_config_json: parseJsonObjectText(providerForm.extra_config_text, "Provider extra_config_json"),
      };
      if (providerForm.api_key.trim()) {
        payload.api_key = providerForm.api_key;
      }
      if (providerForm.id) {
        await api.put(`/providers/${providerForm.id}`, payload);
      } else {
        await api.post("/providers", payload);
      }
      setProviderForm({ ...emptyProvider, provider_type: providerForm.provider_type });
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Provider 保存失败");
    }
  }

  async function saveModel(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const payload = {
        provider_id: modelForm.provider_id,
        model_name: modelForm.model_name,
        temperature: modelForm.temperature,
        max_tokens: modelForm.max_tokens,
        top_p: modelForm.top_p.trim() ? Number(modelForm.top_p) : null,
        stream_enabled: modelForm.stream_enabled,
        formatter_type: modelForm.formatter_type,
        extra_config_json: parseJsonObjectText(modelForm.extra_config_text, "Model extra_config_json"),
      };
      if (modelForm.id) {
        await api.put(`/models/${modelForm.id}`, payload);
      } else {
        await api.post("/models", payload);
      }
      setModelForm((prev) => ({ ...emptyModel, provider_id: prev.provider_id || providers[0]?.id || "" }));
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Model 保存失败");
    }
  }

  async function testProvider(providerId: string) {
    const result = await api.post<ConnectionTestResult>(`/providers/${providerId}/test`);
    setTesting((prev) => ({ ...prev, [providerId]: result }));
  }

  async function testModel(modelId: string) {
    const result = await api.post<ConnectionTestResult>(`/models/${modelId}/test`);
    setTesting((prev) => ({ ...prev, [modelId]: result }));
  }

  function startEditProvider(provider: Provider) {
    setProviderForm({
      id: provider.id,
      provider_type: provider.provider_type,
      name: provider.name,
      api_key: "",
      base_url: provider.base_url ?? "",
      organization: provider.organization ?? "",
      extra_config_text: prettyJson(provider.extra_config_json ?? {}),
    });
  }

  function startEditModel(model: ModelConfig) {
    setModelForm({
      id: model.id,
      provider_id: model.provider_id,
      model_name: model.model_name,
      temperature: model.temperature ?? 0.7,
      max_tokens: model.max_tokens ?? 1024,
      top_p: model.top_p == null ? "" : String(model.top_p),
      stream_enabled: Boolean(model.stream_enabled),
      formatter_type: model.formatter_type ?? "auto",
      extra_config_text: prettyJson(model.extra_config_json ?? {}),
    });
  }

  async function deleteProvider(providerId: string) {
    await api.del(`/providers/${providerId}`);
    await loadAll();
  }

  async function deleteModel(modelId: string) {
    await api.del(`/models/${modelId}`);
    await loadAll();
  }

  return {
    providers,
    providerModelMap,
    providerForm,
    setProviderForm,
    modelForm,
    setModelForm,
    error,
    setError,
    testing,
    saveProvider,
    saveModel,
    testProvider,
    testModel,
    startEditProvider,
    startEditModel,
    deleteProvider,
    deleteModel,
  };
}
