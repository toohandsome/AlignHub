"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { AgentAvatar } from "@/components/discussion-ui";
import { Card, Input, PrimaryButton, SecondaryButton, SectionTitle, Select, Textarea } from "@/components/ui";
import { AgentConfig, api, FeishuAgentBotConfig, FeishuChatDiagnoseItem } from "@/lib/api";

type BotForm = {
  agent_id: string;
  app_id: string;
  app_secret: string;
  verification_token: string;
  bot_name: string;
  enabled: boolean;
  receive_enabled: boolean;
};

const emptyForm: BotForm = {
  agent_id: "",
  app_id: "",
  app_secret: "",
  verification_token: "",
  bot_name: "",
  enabled: true,
  receive_enabled: false
};

export default function FeishuBotsPage() {
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [bots, setBots] = useState<FeishuAgentBotConfig[]>([]);
  const [form, setForm] = useState<BotForm>(emptyForm);
  const [testChatId, setTestChatId] = useState("");
  const [testText, setTestText] = useState("这是一条以 Agent Bot 身份发送的测试消息。");
  const [diagnoseChatId, setDiagnoseChatId] = useState("");
  const [diagnoseResults, setDiagnoseResults] = useState<FeishuChatDiagnoseItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  /**
   * Agent 列表与 Agent Bot 配置需要联合展示，
   * 便于识别哪些 Agent 尚未绑定机器人。
   */
  async function loadAll() {
    const [agentData, botData] = await Promise.all([
      api.get<AgentConfig[]>("/agents"),
      api.get<FeishuAgentBotConfig[]>("/integrations/feishu/agent-bots")
    ]);
    setAgents(agentData);
    setBots(botData);
    setForm((prev) => ({ ...prev, agent_id: prev.agent_id || agentData[0]?.id || "" }));
  }

  useEffect(() => {
    loadAll().catch((err) => setError(err.message));
  }, []);

  const botMap = useMemo(() => Object.fromEntries(bots.map((bot) => [bot.agent_id, bot])), [bots]);

  function resetForm() {
    setForm({ ...emptyForm, agent_id: agents[0]?.id || "" });
    setError("");
    setMessage("");
  }

  /**
   * 编辑时实时从后端读取最新 bot 配置，
   * 避免列表里的脱敏字段不完整。
   */
  async function startEdit(agentId: string) {
    const bot = await api.get<FeishuAgentBotConfig>(`/agents/${agentId}/feishu-bot`);
    setForm({
      agent_id: agentId,
      app_id: bot.app_id ?? "",
      app_secret: bot.app_secret ?? "",
      verification_token: bot.verification_token ?? "",
      bot_name: bot.bot_name ?? "",
      enabled: Boolean(bot.enabled),
      receive_enabled: Boolean(bot.receive_enabled)
    });
    setError("");
    setMessage("");
  }

  async function saveBot(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await api.put<FeishuAgentBotConfig>(`/agents/${form.agent_id}/feishu-bot`, {
        app_id: form.app_id,
        app_secret: form.app_secret,
        verification_token: form.verification_token,
        bot_name: form.bot_name || null,
        enabled: form.enabled,
        receive_enabled: form.receive_enabled
      });
      await loadAll();
      setMessage("Agent Bot 配置已保存。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setLoading(false);
    }
  }

  async function deleteBot(agentId: string) {
    if (!window.confirm("确认解绑这个 Agent 的飞书机器人吗？")) return;
    setError("");
    setMessage("");
    try {
      await api.del(`/agents/${agentId}/feishu-bot`);
      if (form.agent_id === agentId) resetForm();
      await loadAll();
      setMessage("已解绑飞书机器人。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "解绑失败");
    }
  }

  async function testSend() {
    setTesting(true);
    setError("");
    setMessage("");
    try {
      await api.post("/integrations/feishu/test-send", {
        chat_id: testChatId,
        text: testText,
        agent_id: form.agent_id || null
      });
      setMessage("测试消息已发送。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试发送失败");
    } finally {
      setTesting(false);
    }
  }

  /**
   * 诊断接口会逐个检查 Agent Bot 是否在目标 chat_id 中，
   * 适合排查“能发消息但群内不可见”这类问题。
   */
  async function diagnoseChat() {
    setDiagnosing(true);
    setError("");
    setMessage("");
    try {
      const result = await api.post<FeishuChatDiagnoseItem[]>("/integrations/feishu/diagnose-chat", {
        chat_id: diagnoseChatId
      });
      setDiagnoseResults(result);
      setMessage("chat_id 诊断完成。");
    } catch (err) {
      setDiagnoseResults([]);
      setError(err instanceof Error ? err.message : "诊断失败");
    } finally {
      setDiagnosing(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.95fr)]">
      <Card>
        <SectionTitle title="Agent Bot 列表" desc="每个 Agent 可绑定一个独立飞书机器人身份，用于按角色发言或直连接收消息。" />
        <div className="grid gap-3">
          {agents.map((agent) => {
            const bot = botMap[agent.id];
            return (
              <div key={agent.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-3">
                      <AgentAvatar seed={agent.id} name={agent.name} className="h-11 w-11" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium text-[var(--text)]">{agent.name}</div>
                        <div className="truncate text-xs text-sky-500">{agent.role}</div>
                      </div>
                    </div>
                    <div className="mt-3 grid gap-1 text-xs text-[var(--muted)]">
                      <div>机器人名称：{bot?.bot_name ?? "未配置"}</div>
                      <div>App ID：{bot?.app_id ?? "-"}</div>
                      <div>状态：{bot?.enabled ? "已启用" : "未启用"}</div>
                      <div>接收事件：{bot?.receive_enabled ? "开启" : "关闭"}</div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <PrimaryButton type="button" onClick={() => startEdit(agent.id).catch((err) => setError(err.message))}>
                      {bot ? "编辑" : "配置"}
                    </PrimaryButton>
                    {bot ? (
                      <SecondaryButton type="button" onClick={() => deleteBot(agent.id)}>
                        解绑
                      </SecondaryButton>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <div className="grid gap-6">
        <Card>
          <SectionTitle title="配置 Agent Bot" desc="为指定 Agent 绑定独立飞书机器人。" />
          <form onSubmit={saveBot} className="space-y-3">
            <Select value={form.agent_id} onChange={(e) => setForm((prev) => ({ ...prev, agent_id: e.target.value }))}>
              <option value="">选择 Agent</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </Select>
            <Input value={form.app_id} onChange={(e) => setForm((prev) => ({ ...prev, app_id: e.target.value }))} placeholder="飞书 Bot App ID" />
            <Input value={form.bot_name} onChange={(e) => setForm((prev) => ({ ...prev, bot_name: e.target.value }))} placeholder="飞书机器人显示名" />
            <Input value={form.app_secret} onChange={(e) => setForm((prev) => ({ ...prev, app_secret: e.target.value }))} placeholder="飞书 Bot App Secret（留空表示不修改）" />
            <Input value={form.verification_token} onChange={(e) => setForm((prev) => ({ ...prev, verification_token: e.target.value }))} placeholder="Verification Token（留空表示不修改）" />
            <label className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]">
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm((prev) => ({ ...prev, enabled: e.target.checked }))} />
              <span>启用该 Agent Bot</span>
            </label>
            <label className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]">
              <input type="checkbox" checked={form.receive_enabled} onChange={(e) => setForm((prev) => ({ ...prev, receive_enabled: e.target.checked }))} />
              <span>允许该 Agent Bot 直连接收飞书事件</span>
            </label>

            <div className="flex flex-wrap gap-3">
              <PrimaryButton type="submit" disabled={loading || !form.agent_id || !form.app_id || !form.app_secret || !form.verification_token}>
                {loading ? "保存中..." : "保存配置"}
              </PrimaryButton>
              <SecondaryButton type="button" onClick={resetForm}>
                重置
              </SecondaryButton>
            </div>
          </form>
        </Card>

        <Card>
          <SectionTitle title="测试按 Agent 身份发消息" desc="可验证该 Agent Bot 的发消息能力是否正常。" />
          <div className="space-y-3">
            <Input value={testChatId} onChange={(e) => setTestChatId(e.target.value)} placeholder="目标 chat_id" />
            <Textarea value={testText} onChange={(e) => setTestText(e.target.value)} placeholder="测试消息内容" />
            <PrimaryButton type="button" disabled={testing || !testChatId || !form.agent_id} onClick={testSend}>
              {testing ? "发送中..." : "用当前 Agent Bot 测试发送"}
            </PrimaryButton>
          </div>
        </Card>

        <Card>
          <SectionTitle title="诊断 chat_id" desc="输入飞书群 chat_id，检查每个 Agent Bot 是否被飞书判定在该群中。" />
          <div className="space-y-3">
            <Input value={diagnoseChatId} onChange={(e) => setDiagnoseChatId(e.target.value)} placeholder="待诊断的 chat_id" />
            <PrimaryButton type="button" disabled={diagnosing || !diagnoseChatId} onClick={diagnoseChat}>
              {diagnosing ? "诊断中..." : "诊断 chat_id"}
            </PrimaryButton>
            {diagnoseResults.length ? (
              <div className="grid gap-2">
                {diagnoseResults.map((item) => (
                  <div key={item.agent_id} className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--text)]">
                    <div className="font-medium">{item.agent_name}{item.bot_name ? `（${item.bot_name}）` : ""}</div>
                    <div className="mt-1 text-xs text-[var(--muted)]">App ID：{item.app_id || "-"}</div>
                    <div className="mt-1 text-xs text-[var(--muted)]">启用：{item.enabled ? "是" : "否"} / 接收事件：{item.receive_enabled ? "是" : "否"}</div>
                    <div className="mt-1 text-xs">
                      诊断结果：
                      <span className={item.in_chat === true ? "text-emerald-500" : item.in_chat === false ? "text-amber-500" : "text-slate-400"}>
                        {item.in_chat === true ? " 在群内" : item.in_chat === false ? " 不在群内" : " 未知"}
                      </span>
                    </div>
                    {item.error ? <div className="mt-1 text-xs text-rose-500">错误：{item.error}</div> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </Card>

        {error ? <p className="text-sm text-rose-500">{error}</p> : null}
        {message ? <p className="text-sm text-emerald-500">{message}</p> : null}
      </div>
    </div>
  );
}
