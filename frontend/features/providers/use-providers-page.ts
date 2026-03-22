"use client";

import { useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/ui";
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
  extra_config_text: "{}"
};

export const emptyModel: ModelForm = {
  provider_id: "",
  model_name: "",
  temperature: 0.7,
  max_tokens: 1024,
  top_p: "",
  stream_enabled: false,
  formatter_type: "auto",
  extra_config_text: "{}"
};

export function useProvidersPage() {
  const { toast } = useToast();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [providerForm, setProviderForm] = useState<ProviderForm>(emptyProvider);
  const [modelForm, setModelForm] = useState<ModelForm>(emptyModel);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState<Record<string, ConnectionTestResult>>({});
  const [bootstrapping, setBootstrapping] = useState(true);
  const [submitting, setSubmitting] = useState<"provider" | "model" | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  async function loadAll(showLoader = false) {
    if (showLoader) setBootstrapping(true);
    try {
      const [providerData, modelData] = await Promise.all([api.get<Provider[]>("/providers"), api.get<ModelConfig[]>("/models")]);
      setProviders(providerData);
      setModels(modelData);
      setModelForm((prev) => ({ ...prev, provider_id: prev.provider_id || providerData[0]?.id || "" }));
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "加载 Provider / Model 失败";
      setError(message);
    } finally {
      if (showLoader) setBootstrapping(false);
    }
  }

  useEffect(() => {
    void loadAll(true);
  }, []);

  const providerModelMap = useMemo(
    () => providers.map((provider) => ({ provider, models: models.filter((model) => model.provider_id === provider.id) })),
    [providers, models]
  );

  async function saveProvider() {
    setSubmitting("provider");
    setError("");
    try {
      const payload: Record<string, unknown> = {
        provider_type: providerForm.provider_type,
        name: providerForm.name.trim(),
        base_url: providerForm.base_url.trim() || null,
        organization: providerForm.organization.trim() || null,
        extra_config_json: parseJsonObjectText(providerForm.extra_config_text, "Provider extra_config_json")
      };
      if (providerForm.api_key.trim()) {
        payload.api_key = providerForm.api_key.trim();
      }
      if (providerForm.id) {
        await api.put(`/providers/${providerForm.id}`, payload);
      } else {
        await api.post("/providers", payload);
      }
      setProviderForm({ ...emptyProvider, provider_type: providerForm.provider_type });
      await loadAll();
      toast({
        tone: "success",
        title: providerForm.id ? "Provider 已更新" : "Provider 已创建",
        description: `${providerForm.name.trim()} 已同步到配置列表。`
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存 Provider 失败";
      setError(message);
      toast({ tone: "danger", title: "保存 Provider 失败", description: message });
      throw err;
    } finally {
      setSubmitting(null);
    }
  }

  async function saveModel() {
    setSubmitting("model");
    setError("");
    try {
      const payload = {
        provider_id: modelForm.provider_id,
        model_name: modelForm.model_name.trim(),
        temperature: modelForm.temperature,
        max_tokens: modelForm.max_tokens,
        top_p: modelForm.top_p.trim() ? Number(modelForm.top_p) : null,
        stream_enabled: modelForm.stream_enabled,
        formatter_type: modelForm.formatter_type.trim() || "auto",
        extra_config_json: parseJsonObjectText(modelForm.extra_config_text, "Model extra_config_json")
      };
      if (modelForm.id) {
        await api.put(`/models/${modelForm.id}`, payload);
      } else {
        await api.post("/models", payload);
      }
      setModelForm((prev) => ({ ...emptyModel, provider_id: prev.provider_id || providers[0]?.id || "" }));
      await loadAll();
      toast({
        tone: "success",
        title: modelForm.id ? "Model 已更新" : "Model 已创建",
        description: `${modelForm.model_name.trim()} 已可用于 Agent 绑定。`
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存 Model 失败";
      setError(message);
      toast({ tone: "danger", title: "保存 Model 失败", description: message });
      throw err;
    } finally {
      setSubmitting(null);
    }
  }

  async function testProvider(providerId: string) {
    setTestingId(providerId);
    try {
      const result = await api.post<ConnectionTestResult>(`/providers/${providerId}/test`);
      setTesting((prev) => ({ ...prev, [providerId]: result }));
      toast({
        tone: result.success ? "success" : "danger",
        title: result.success ? "Provider 连通成功" : "Provider 连通失败",
        description: result.message || result.error || "已更新测试结果。"
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "测试 Provider 失败";
      setError(message);
      toast({ tone: "danger", title: "测试 Provider 失败", description: message });
    } finally {
      setTestingId(null);
    }
  }

  async function testModel(modelId: string) {
    setTestingId(modelId);
    try {
      const result = await api.post<ConnectionTestResult>(`/models/${modelId}/test`);
      setTesting((prev) => ({ ...prev, [modelId]: result }));
      toast({
        tone: result.success ? "success" : "danger",
        title: result.success ? "Model 连通成功" : "Model 连通失败",
        description: result.message || result.error || "已更新测试结果。"
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "测试 Model 失败";
      setError(message);
      toast({ tone: "danger", title: "测试 Model 失败", description: message });
    } finally {
      setTestingId(null);
    }
  }

  function startEditProvider(provider: Provider) {
    setProviderForm({
      id: provider.id,
      provider_type: provider.provider_type,
      name: provider.name,
      api_key: "",
      base_url: provider.base_url ?? "",
      organization: provider.organization ?? "",
      extra_config_text: prettyJson(provider.extra_config_json ?? {})
    });
    setError("");
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
      extra_config_text: prettyJson(model.extra_config_json ?? {})
    });
    setError("");
  }

  async function deleteProvider(providerId: string) {
    const target = providers.find((item) => item.id === providerId);
    setRemovingId(providerId);
    try {
      await api.del(`/providers/${providerId}`);
      await loadAll();
      toast({ tone: "success", title: "Provider 已删除", description: target?.name ? `${target.name} 已从配置中移除。` : undefined });
    } catch (err) {
      const message = err instanceof Error ? err.message : "删除 Provider 失败";
      setError(message);
      toast({ tone: "danger", title: "删除 Provider 失败", description: message });
    } finally {
      setRemovingId(null);
    }
  }

  async function deleteModel(modelId: string) {
    const target = models.find((item) => item.id === modelId);
    setRemovingId(modelId);
    try {
      await api.del(`/models/${modelId}`);
      await loadAll();
      toast({ tone: "success", title: "Model 已删除", description: target?.model_name ? `${target.model_name} 已从列表移除。` : undefined });
    } catch (err) {
      const message = err instanceof Error ? err.message : "删除 Model 失败";
      setError(message);
      toast({ tone: "danger", title: "删除 Model 失败", description: message });
    } finally {
      setRemovingId(null);
    }
  }

  return {
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
  };
}
