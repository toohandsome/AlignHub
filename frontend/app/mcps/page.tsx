"use client";

import { useEffect, useMemo, useState } from "react";

import { Badge, Card, CheckboxRow, EmptyState, Field, InlineAlert, Input, PrimaryButton, SecondaryButton, SectionTitle, Select, Skeleton, Textarea, useToast } from "@/components/ui";
import { api, MCPServerConfig, MCPTestResult } from "@/lib/api";
import { focusField, getJsonArrayError, getJsonObjectError } from "@/lib/form-feedback";

type MCPForm = {
  id?: string;
  name: string;
  transport_type: string;
  description: string;
  command: string;
  args_text: string;
  env_text: string;
  base_url: string;
  enabled: boolean;
};

const emptyMcp: MCPForm = {
  name: "",
  transport_type: "stdio",
  description: "",
  command: "",
  args_text: "[]",
  env_text: "{}",
  base_url: "",
  enabled: true
};

export default function McpsPage() {
  const { toast } = useToast();
  const [mcps, setMcps] = useState<MCPServerConfig[]>([]);
  const [form, setForm] = useState<MCPForm>(emptyMcp);
  const [error, setError] = useState("");
  const [connectionTests, setConnectionTests] = useState<Record<string, MCPTestResult>>({});
  const [invokeTests, setInvokeTests] = useState<Record<string, MCPTestResult>>({});
  const [startupPreviews, setStartupPreviews] = useState<Record<string, MCPTestResult>>({});
  const [jarFile, setJarFile] = useState<File | null>(null);
  const [jarName, setJarName] = useState("");
  const [jarDescription, setJarDescription] = useState("");
  const [jarArgsText, setJarArgsText] = useState("[]");
  const [bootstrapping, setBootstrapping] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function loadAll(showLoader = false) {
    if (showLoader) setBootstrapping(true);
    try {
      const data = await api.get<MCPServerConfig[]>("/mcps");
      setMcps(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 MCP 列表失败");
    } finally {
      if (showLoader) setBootstrapping(false);
    }
  }

  useEffect(() => {
    void loadAll(true);
  }, []);

  const formErrors = useMemo(
    () => ({
      name: form.name.trim() ? "" : "请输入 MCP 名称",
      description: form.description.trim() ? "" : "请输入 MCP 描述",
      args_text: getJsonArrayError(form.args_text, "Args JSON"),
      env_text: getJsonObjectError(form.env_text, "Env JSON")
    }),
    [form]
  );

  async function saveMcp(event: React.FormEvent) {
    event.preventDefault();
    const firstError = Object.entries(formErrors).find(([, value]) => value)?.[0];
    if (firstError) {
      focusField(firstError);
      return;
    }

    setSaving(true);
    setError("");
    try {
      const payload = {
        name: form.name.trim(),
        transport_type: form.transport_type,
        description: form.description.trim(),
        command: form.command.trim() || null,
        args_json: JSON.parse(form.args_text || "[]"),
        env_json: JSON.parse(form.env_text || "{}"),
        base_url: form.base_url.trim() || null,
        jar_path: null,
        enabled: form.enabled
      };
      if (form.id) await api.put(`/mcps/${form.id}`, payload);
      else await api.post("/mcps", payload);
      const mcpName = form.name.trim();
      setForm(emptyMcp);
      await loadAll();
      toast({ tone: "success", title: form.id ? "MCP 已更新" : "MCP 已创建", description: `${mcpName} 已可用于 Agent 挂载。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存 MCP 失败";
      setError(message);
      toast({ tone: "danger", title: "保存 MCP 失败", description: message });
    } finally {
      setSaving(false);
    }
  }

  async function uploadJar(event: React.FormEvent) {
    event.preventDefault();
    if (!jarFile) {
      setError("请先选择 jar 包");
      toast({ tone: "warn", title: "缺少文件", description: "请先选择 jar 文件后再上传。" });
      return;
    }
    if (getJsonArrayError(jarArgsText, "Jar Args JSON")) {
      setError(getJsonArrayError(jarArgsText, "Jar Args JSON"));
      focusField("jarArgsText");
      return;
    }

    setUploading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", jarFile);
      if (jarName) formData.append("name", jarName);
      if (jarDescription) formData.append("description", jarDescription);
      formData.append("args_json", jarArgsText || "[]");
      formData.append("enabled", "true");
      await api.upload<MCPServerConfig>("/mcps/upload-jar", formData);
      setJarFile(null);
      setJarName("");
      setJarDescription("");
      setJarArgsText("[]");
      await loadAll();
      toast({ tone: "success", title: "Jar 上传成功", description: `${jarFile.name} 已自动转换为 MCP 配置。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "上传 Jar 失败";
      setError(message);
      toast({ tone: "danger", title: "上传 Jar 失败", description: message });
    } finally {
      setUploading(false);
    }
  }

  async function testConnection(mcpId: string) {
    setBusyId(mcpId);
    try {
      const result = await api.post<MCPTestResult>(`/mcps/${mcpId}/test`);
      setConnectionTests((prev) => ({ ...prev, [mcpId]: result }));
      toast({ tone: result.success ? "success" : "danger", title: result.success ? "连接测试成功" : "连接测试失败", description: result.error || result.preview || "已更新测试结果。" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "测试 MCP 连接失败";
      setError(message);
      toast({ tone: "danger", title: "测试连接失败", description: message });
    } finally {
      setBusyId(null);
    }
  }

  async function testInvoke(mcpId: string) {
    setBusyId(mcpId);
    try {
      const result = await api.post<MCPTestResult>(`/mcps/${mcpId}/invoke-test`, { action: "ping", payload_json: {} });
      setInvokeTests((prev) => ({ ...prev, [mcpId]: result }));
      toast({ tone: result.success ? "success" : "danger", title: result.success ? "调用测试成功" : "调用测试失败", description: result.error || result.preview || "已更新调用结果。" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "测试 MCP 调用失败";
      setError(message);
      toast({ tone: "danger", title: "测试调用失败", description: message });
    } finally {
      setBusyId(null);
    }
  }

  async function previewStartup(mcpId: string) {
    setBusyId(mcpId);
    try {
      const result = await api.post<MCPTestResult>(`/mcps/${mcpId}/startup-preview`);
      setStartupPreviews((prev) => ({ ...prev, [mcpId]: result }));
      toast({ tone: result.success ? "success" : "default", title: "启动预览已更新", description: result.error || result.preview || "可在列表中查看详情。" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "获取 MCP 启动预览失败";
      setError(message);
      toast({ tone: "danger", title: "启动预览失败", description: message });
    } finally {
      setBusyId(null);
    }
  }

  async function removeMcp(mcp: MCPServerConfig) {
    setBusyId(mcp.id);
    try {
      await api.del(`/mcps/${mcp.id}`);
      await loadAll();
      toast({ tone: "success", title: "MCP 已删除", description: `${mcp.name} 已从列表移除。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "删除 MCP 失败";
      setError(message);
      toast({ tone: "danger", title: "删除 MCP 失败", description: message });
    } finally {
      setBusyId(null);
    }
  }

  if (bootstrapping) {
    return (
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <Skeleton className="h-[900px]" />
        <div className="grid gap-6">
          <Skeleton className="h-[310px]" />
          <Skeleton className="h-[560px]" />
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="External Capability" title="MCP 管理台" desc="统一接入 stdio / http / sse / jar 能力，支持连接测试、调用测试和启动预览。" />
        <div className="flex flex-wrap gap-2">
          <Badge>{mcps.length} 个 MCP</Badge>
          <Badge tone="success">{mcps.filter((mcp) => mcp.enabled).length} 个已启用</Badge>
          <Badge tone="warn">支持 Jar 自动导入</Badge>
        </div>
      </Card>

      {error ? <InlineAlert tone="danger" title="MCP 页面操作失败" description={error} /> : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <Card>
          <SectionTitle eyebrow="Registry" title="MCP 列表" desc="MCP 会在 Agent 配置页中作为可挂载能力出现。" />
          <div className="mb-4 rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] p-4 text-sm text-[var(--muted)]">
            <div className="font-medium text-[var(--text)]">调用约定</div>
            <pre className="mt-2 overflow-x-auto rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{`tool(action, payload_json)

stdio: stdin <- JSON, env <- env_json
http: GET {base_url}, POST {base_url}/invoke
sse: GET {base_url}, POST {base_url}/invoke
jar: java -jar <artifact>.jar`}</pre>
          </div>
          <div className="grid gap-3">
            {mcps.map((mcp) => (
              <div key={mcp.id} className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="text-lg font-semibold text-[var(--text)]">{mcp.name}</div>
                      <Badge>{mcp.transport_type}</Badge>
                      <Badge tone={mcp.enabled ? "success" : "warn"}>{mcp.enabled ? "enabled" : "disabled"}</Badge>
                    </div>
                    <div className="mt-2 text-sm leading-7 text-[var(--muted)]">{mcp.description}</div>
                    <div className="mt-3 grid gap-1 text-xs text-[var(--muted)]">
                      <div>Command：{mcp.command || "-"}</div>
                      <div>Base URL：{mcp.base_url || "-"}</div>
                      {mcp.jar_path ? <div className="break-all">Jar Path：{mcp.jar_path}</div> : null}
                    </div>
                    <pre className="mt-3 whitespace-pre-wrap break-all rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify({ args_json: mcp.args_json, env_json: mcp.env_json }, null, 2)}</pre>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <SecondaryButton type="button" loading={busyId === mcp.id} onClick={() => void testConnection(mcp.id)}>
                      测试连接
                    </SecondaryButton>
                    <SecondaryButton type="button" loading={busyId === mcp.id} onClick={() => void testInvoke(mcp.id)}>
                      测试调用
                    </SecondaryButton>
                    <SecondaryButton type="button" loading={busyId === mcp.id} onClick={() => void previewStartup(mcp.id)}>
                      启动预览
                    </SecondaryButton>
                    <PrimaryButton
                      type="button"
                      onClick={() =>
                        setForm({
                          id: mcp.id,
                          name: mcp.name,
                          transport_type: mcp.transport_type,
                          description: mcp.description,
                          command: mcp.command ?? "",
                          args_text: JSON.stringify(mcp.args_json, null, 2),
                          env_text: JSON.stringify(mcp.env_json, null, 2),
                          base_url: mcp.base_url ?? "",
                          enabled: mcp.enabled
                        })
                      }
                    >
                      编辑
                    </PrimaryButton>
                    <SecondaryButton
                      type="button"
                      loading={busyId === mcp.id}
                      onClick={() => {
                        if (!window.confirm(`确认删除 MCP “${mcp.name}” 吗？`)) return;
                        void removeMcp(mcp);
                      }}
                    >
                      删除
                    </SecondaryButton>
                  </div>
                </div>
                {connectionTests[mcp.id] ? <pre className="mt-3 whitespace-pre-wrap break-all rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(connectionTests[mcp.id], null, 2)}</pre> : null}
                {invokeTests[mcp.id] ? <pre className="mt-3 whitespace-pre-wrap break-all rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(invokeTests[mcp.id], null, 2)}</pre> : null}
                {startupPreviews[mcp.id] ? <pre className="mt-3 whitespace-pre-wrap break-all rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(startupPreviews[mcp.id], null, 2)}</pre> : null}
              </div>
            ))}
            {!mcps.length ? <EmptyState title="还没有 MCP" description="你可以手动创建一个 MCP，或通过 Jar 上传快速导入。" /> : null}
          </div>
        </Card>

        <div className="grid gap-6">
          <Card>
            <SectionTitle eyebrow="Jar Import" title="上传 MCP Jar" desc="适用于 Java MCP 服务，后端会自动生成 java -jar 运行配置。" />
            <form onSubmit={uploadJar} className="space-y-4">
              <Field label="Jar 文件" hint={jarFile ? jarFile.name : "仅支持 .jar"}>
                <Input type="file" accept=".jar" onChange={(e) => setJarFile(e.target.files?.[0] ?? null)} />
              </Field>
              <Field label="覆盖名称">
                <Input placeholder="可选：覆盖 MCP 名称" value={jarName} onChange={(e) => setJarName(e.target.value)} />
              </Field>
              <Field label="描述">
                <Input placeholder="可选：Jar 描述" value={jarDescription} onChange={(e) => setJarDescription(e.target.value)} />
              </Field>
              <Field label="启动参数 JSON" error={getJsonArrayError(jarArgsText, "Jar Args JSON")}>
                <Textarea name="jarArgsText" placeholder='例如：["--server.port=8081"]' value={jarArgsText} invalid={Boolean(getJsonArrayError(jarArgsText, "Jar Args JSON"))} onChange={(e) => setJarArgsText(e.target.value)} />
              </Field>
              <PrimaryButton type="submit" loading={uploading}>
                上传 Jar 并创建 MCP
              </PrimaryButton>
            </form>
          </Card>

          <Card>
            <SectionTitle eyebrow="Manual" title={form.id ? "编辑 MCP" : "创建 MCP"} desc="适用于 stdio / http / sse 三类传输配置。" />
            <form onSubmit={saveMcp} className="space-y-4">
              <Field label="MCP 名称" required error={formErrors.name}>
                <Input name="name" placeholder="例如：CRM Connector" value={form.name} invalid={Boolean(formErrors.name)} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label="传输类型">
                <Select value={form.transport_type} onChange={(e) => setForm({ ...form, transport_type: e.target.value })}>
                  <option value="stdio">stdio</option>
                  <option value="http">http</option>
                  <option value="sse">sse</option>
                </Select>
              </Field>
              <Field label="描述" required error={formErrors.description}>
                <Input name="description" placeholder="描述这个 MCP 提供的业务能力" value={form.description} invalid={Boolean(formErrors.description)} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </Field>
              <Field label="Command">
                <Input placeholder="stdio 可选" value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} />
              </Field>
              <Field label="Base URL">
                <Input placeholder="http / sse 可选" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
              </Field>
              <Field label="Args JSON" error={formErrors.args_text}>
                <Textarea name="args_text" placeholder='例如：["server.py","--port","9000"]' value={form.args_text} invalid={Boolean(formErrors.args_text)} onChange={(e) => setForm({ ...form, args_text: e.target.value })} />
              </Field>
              <Field label="Env JSON" error={formErrors.env_text}>
                <Textarea name="env_text" placeholder='例如：{"API_KEY":"xxx"}' value={form.env_text} invalid={Boolean(formErrors.env_text)} onChange={(e) => setForm({ ...form, env_text: e.target.value })} />
              </Field>
              <CheckboxRow checked={form.enabled} onChange={(checked) => setForm({ ...form, enabled: checked })} label="启用 MCP" description="禁用后不会在 Agent 页面参与挂载。" />
              <div className="flex gap-3">
                <PrimaryButton type="submit" loading={saving}>
                  {form.id ? "保存 MCP" : "创建 MCP"}
                </PrimaryButton>
                {form.id ? (
                  <SecondaryButton type="button" onClick={() => setForm(emptyMcp)}>
                    取消编辑
                  </SecondaryButton>
                ) : null}
              </div>
            </form>
          </Card>
        </div>
      </div>
    </div>
  );
}
