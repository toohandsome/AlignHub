"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { Badge, Card, Input, PrimaryButton, SectionTitle, SecondaryButton, Textarea } from "@/components/ui";
import { AgentConfig, api, API_BASE, FeishuConfig } from "@/lib/api";

type ConfigForm = {
  appId: string;
  appSecret: string;
  verificationToken: string;
  botName: string;
  enabled: boolean;
};

const emptyForm: ConfigForm = {
  appId: "",
  appSecret: "",
  verificationToken: "",
  botName: "",
  enabled: true
};

export default function FeishuExtensionPage() {
  const [form, setForm] = useState<ConfigForm>(emptyForm);
  const [config, setConfig] = useState<FeishuConfig | null>(null);
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [testChatId, setTestChatId] = useState("");
  const [testText, setTestText] = useState("这是一条来自 AgentScope 的飞书测试消息。");
  const [testAgentId, setTestAgentId] = useState("");
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  /**
   * 飞书主配置与 Agent 列表要同时展示，方便用户直接选择测试发送身份。
   */
  async function loadConfig() {
    const [data, agentData] = await Promise.all([
      api.get<FeishuConfig>("/integrations/feishu/config"),
      api.get<AgentConfig[]>("/agents")
    ]);
    setConfig(data);
    setAgents(agentData);
    setForm({
      appId: data.app_id ?? "",
      appSecret: data.app_secret ?? "",
      verificationToken: data.verification_token ?? "",
      botName: data.bot_name ?? "",
      enabled: data.enabled ?? true
    });
  }

  useEffect(() => {
    loadConfig().catch((err) => setError(err.message));
  }, []);

  async function saveConfig(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await api.put("/integrations/feishu/config", {
        app_id: form.appId,
        app_secret: form.appSecret,
        verification_token: form.verificationToken,
        bot_name: form.botName || null,
        enabled: form.enabled
      });
      await loadConfig();
      setMessage("飞书配置已保存。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存飞书配置失败");
    } finally {
      setLoading(false);
    }
  }

  /**
   * 测试消息支持指定 agent_id，便于验证 Host 机器人和 Agent Bot 两种发送路径。
   */
  async function sendTest() {
    setTesting(true);
    setError("");
    setMessage("");
    try {
      await api.post("/integrations/feishu/test-send", {
        chat_id: testChatId,
        text: testText,
        agent_id: testAgentId || null
      });
      setMessage("测试消息已发送。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送测试消息失败");
    } finally {
      setTesting(false);
    }
  }

  const webhookPath = config?.webhook_path ?? "/api/v1/integrations/feishu/events";
  const webhookHint = `${API_BASE.replace("/api/v1", "")}${webhookPath}`;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)]">
      <Card>
        <SectionTitle title="飞书集成配置" desc="第一版采用单主持机器人接入飞书群聊，由后端统一编排多 Agent 讨论。" />
        <form onSubmit={saveConfig} className="space-y-3">
          <Input value={form.appId} onChange={(e) => setForm((prev) => ({ ...prev, appId: e.target.value }))} placeholder="飞书 App ID" />
          <Input value={form.botName} onChange={(e) => setForm((prev) => ({ ...prev, botName: e.target.value }))} placeholder="机器人显示名（可选）" />
          <Input value={form.appSecret} onChange={(e) => setForm((prev) => ({ ...prev, appSecret: e.target.value }))} placeholder="App Secret" />
          <Input value={form.verificationToken} onChange={(e) => setForm((prev) => ({ ...prev, verificationToken: e.target.value }))} placeholder="Verification Token" />

          <label className="flex items-center gap-3 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--text)]">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm((prev) => ({ ...prev, enabled: e.target.checked }))} />
            <span>启用飞书集成</span>
          </label>

          <div className="flex flex-wrap gap-3">
            <PrimaryButton type="submit" disabled={loading || !form.appId || !form.appSecret || !form.verificationToken}>
              {loading ? "保存中..." : "保存配置"}
            </PrimaryButton>
            <SecondaryButton type="button" onClick={() => loadConfig().catch((err) => setError(err.message))}>
              刷新
            </SecondaryButton>
          </div>
        </form>

        <div className="mt-6 grid gap-3 rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
          <div className="text-sm font-medium text-[var(--text)]">Webhook 配置</div>
          <Badge>{webhookPath}</Badge>
          <p className="break-all text-sm text-[var(--muted)]">如果当前后端可被公网访问，请在飞书事件订阅中把请求地址配置为：{webhookHint}</p>
          <p className="text-xs text-[var(--muted)]">Host 机器人负责统一接收群事件；第二版支持每个 Agent 绑定独立机器人身份来发言。</p>
        </div>
      </Card>

      <div className="grid gap-6">
        <Card>
          <SectionTitle title="测试发消息" desc="向指定飞书群 chat_id 发送一条测试消息。" />
          <div className="space-y-3">
            <Input value={testChatId} onChange={(e) => setTestChatId(e.target.value)} placeholder="目标 chat_id" />
            <select
              value={testAgentId}
              onChange={(e) => setTestAgentId(e.target.value)}
              className="w-full rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-sky-400"
            >
              <option value="">使用 Host 机器人发送</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                  {agent.feishu_bot_name ? `（${agent.feishu_bot_name}）` : ""}
                </option>
              ))}
            </select>
            <Textarea value={testText} onChange={(e) => setTestText(e.target.value)} placeholder="测试消息内容" />
            <PrimaryButton type="button" disabled={testing || !testChatId || !testText} onClick={sendTest}>
              {testing ? "发送中..." : "发送测试消息"}
            </PrimaryButton>
          </div>
        </Card>

        <Card>
          <SectionTitle title="群内命令" desc="当前第一版推荐使用明确命令，而不是依赖复杂 @ 语义。" />
          <div className="space-y-2 text-sm text-[var(--text)]">
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3">#start 讨论主题</div>
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3">开始讨论：讨论主题</div>
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3">#ask Agent名称: 你的问题</div>
            <div className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3">@Agent名称 你的问题</div>
          </div>
          <p className="mt-3 text-xs text-[var(--muted)]">需要先在“讨论会话”页面为会话填写飞书群 chat_id，并启用飞书接入。</p>
        </Card>

        <Card>
          <SectionTitle title="Agent Bot 管理" desc="每个 Agent 的独立飞书机器人已迁移到独立页面管理。" />
          <Link href="/extensions/feishu/bots" className="block rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
            打开飞书机器人管理页
          </Link>
        </Card>

        {error ? <p className="text-sm text-rose-500">{error}</p> : null}
        {message ? <p className="text-sm text-emerald-500">{message}</p> : null}
      </div>
    </div>
  );
}
