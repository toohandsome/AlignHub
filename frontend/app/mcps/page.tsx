"use client";

import { useEffect, useState } from "react";

import { Badge, Card, Input, PrimaryButton, SecondaryButton, SectionTitle, Select, Textarea } from "@/components/ui";
import { api, MCPServerConfig, MCPTestResult } from "@/lib/api";

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

  async function loadAll() {
    const data = await api.get<MCPServerConfig[]>("/mcps");
    setMcps(data);
  }

  useEffect(() => {
    loadAll().catch((err) => setError(err.message));
  }, []);

  async function saveMcp(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const payload = {
        name: form.name,
        transport_type: form.transport_type,
        description: form.description,
        command: form.command || null,
        args_json: JSON.parse(form.args_text || "[]"),
        env_json: JSON.parse(form.env_text || "{}"),
        base_url: form.base_url || null,
        jar_path: null,
        enabled: form.enabled
      };
      if (form.id) await api.put(`/mcps/${form.id}`, payload);
      else await api.post("/mcps", payload);
      setForm(emptyMcp);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 MCP 失败");
    }
  }

  /**
   * jar 上传和普通 MCP 表单是两条入口：
   * - jar 入口适合 Java MCP 服务
   * - 表单入口适合 stdio/http/sse 手工配置
   */
  async function uploadJar(event: React.FormEvent) {
    event.preventDefault();
    if (!jarFile) {
      setError("请先选择 jar 包");
      return;
    }
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传 jar 失败");
    }
  }

  async function testConnection(mcpId: string) {
    try {
      const result = await api.post<MCPTestResult>(`/mcps/${mcpId}/test`);
      setConnectionTests((prev) => ({ ...prev, [mcpId]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试 MCP 连接失败");
    }
  }

  async function testInvoke(mcpId: string) {
    try {
      const result = await api.post<MCPTestResult>(`/mcps/${mcpId}/invoke-test`, {
        action: "ping",
        payload_json: {}
      });
      setInvokeTests((prev) => ({ ...prev, [mcpId]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试 MCP 调用失败");
    }
  }

  async function previewStartup(mcpId: string) {
    try {
      const result = await api.post<MCPTestResult>(`/mcps/${mcpId}/startup-preview`);
      setStartupPreviews((prev) => ({ ...prev, [mcpId]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取 MCP 启动预览失败");
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
      <Card>
        <SectionTitle title="MCP 列表" desc="MCP 会在 Agent 创建/编辑时挂载，并动态注册为可调用工具。" />
        <div className="mb-4 rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4 text-sm text-[var(--muted)]">
          <div className="font-medium text-[var(--text)]">调用约定</div>
          <pre className="mt-2 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{`tool(action, payload_json)\n\nstdio: stdin <- JSON, env <- env_json\nhttp: GET {base_url}, POST {base_url}/invoke\nsse: GET {base_url} (text/event-stream), POST {base_url}/invoke (text/event-stream)\njar: java -jar <artifact>.jar`}</pre>
        </div>
        <div className="grid gap-3">
          {mcps.map((mcp) => (
            <div key={mcp.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="font-medium text-[var(--text)]">{mcp.name}</div>
                    <Badge>{mcp.transport_type}</Badge>
                    <Badge tone={mcp.enabled ? "success" : "warn"}>{mcp.enabled ? "enabled" : "disabled"}</Badge>
                  </div>
                  <div className="mt-1 text-sm text-[var(--muted)]">{mcp.description}</div>
                  <div className="mt-3 grid gap-1 text-xs text-[var(--muted)]">
                    <div>Command：{mcp.command || "-"}</div>
                    <div>Base URL：{mcp.base_url || "-"}</div>
                    {mcp.jar_path ? <div className="break-all">Jar Path：{mcp.jar_path}</div> : null}
                  </div>
                  <pre className="mt-3 whitespace-pre-wrap break-all rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">
                    {JSON.stringify({ args_json: mcp.args_json, env_json: mcp.env_json }, null, 2)}
                  </pre>
                </div>
                <div className="flex flex-wrap gap-2">
                  <SecondaryButton type="button" onClick={() => testConnection(mcp.id)}>
                    测试连接
                  </SecondaryButton>
                  <SecondaryButton type="button" onClick={() => testInvoke(mcp.id)}>
                    测试调用
                  </SecondaryButton>
                  <SecondaryButton type="button" onClick={() => previewStartup(mcp.id)}>
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
                    onClick={async () => {
                      if (!window.confirm("确认删除这个 MCP 吗？")) return;
                      await api.del(`/mcps/${mcp.id}`);
                      await loadAll();
                    }}
                  >
                    删除
                  </SecondaryButton>
                </div>
              </div>
              {connectionTests[mcp.id] ? <pre className="mt-3 whitespace-pre-wrap break-all rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(connectionTests[mcp.id], null, 2)}</pre> : null}
              {invokeTests[mcp.id] ? <pre className="mt-3 whitespace-pre-wrap break-all rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(invokeTests[mcp.id], null, 2)}</pre> : null}
              {startupPreviews[mcp.id] ? <pre className="mt-3 whitespace-pre-wrap break-all rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(startupPreviews[mcp.id], null, 2)}</pre> : null}
            </div>
          ))}
          {!mcps.length ? <p className="text-sm text-[var(--muted)]">暂无 MCP。</p> : null}
        </div>
      </Card>

      <div className="grid gap-6">
        <Card>
          <SectionTitle title="上传 MCP Jar" desc="支持上传 jar，后台会自动配置为 java -jar 启动方式。" />
          <form onSubmit={uploadJar} className="space-y-3">
            <input
              type="file"
              accept=".jar"
              onChange={(e) => setJarFile(e.target.files?.[0] ?? null)}
              className="block w-full rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <Input placeholder="可选：覆盖 MCP 名称" value={jarName} onChange={(e) => setJarName(e.target.value)} />
            <Input placeholder="可选：Jar 描述" value={jarDescription} onChange={(e) => setJarDescription(e.target.value)} />
            <Textarea placeholder='可选：额外启动参数 JSON，例如：["--server.port=8081"]' value={jarArgsText} onChange={(e) => setJarArgsText(e.target.value)} />
            <PrimaryButton type="submit">上传 Jar 并创建 MCP</PrimaryButton>
          </form>
        </Card>

        <Card>
          <SectionTitle title={form.id ? "编辑 MCP" : "创建 MCP"} desc="MCP 支持 stdio / http / sse 三种传输配置；jar 上传推荐走上方入口。" />
          <form onSubmit={saveMcp} className="space-y-3">
            <Input placeholder="MCP 名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Select value={form.transport_type} onChange={(e) => setForm({ ...form, transport_type: e.target.value })}>
              <option value="stdio">stdio</option>
              <option value="http">http</option>
              <option value="sse">sse</option>
            </Select>
            <Input placeholder="描述" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <Input placeholder="Command（stdio 可选）" value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} />
            <Input placeholder="Base URL（http/sse 可选）" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
            <Textarea placeholder='Args JSON，例如：["server.py", "--port", "9000"]' value={form.args_text} onChange={(e) => setForm({ ...form, args_text: e.target.value })} />
            <Textarea placeholder='Env JSON，例如：{"API_KEY":"xxx"}' value={form.env_text} onChange={(e) => setForm({ ...form, env_text: e.target.value })} />
            <label className="flex items-center gap-2 text-sm text-[var(--text)]">
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              启用 MCP
            </label>
            {error ? <p className="text-sm text-rose-500">{error}</p> : null}
            <div className="flex gap-3">
              <PrimaryButton type="submit">{form.id ? "保存 MCP" : "创建 MCP"}</PrimaryButton>
              {form.id ? (
                <SecondaryButton type="button" onClick={() => setForm(emptyMcp)}>
                  取消
                </SecondaryButton>
              ) : null}
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
