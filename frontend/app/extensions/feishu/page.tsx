"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AgentAvatar } from "@/components/discussion-ui";
import { Badge, Card, CheckboxRow, EmptyState, Field, InlineAlert, Input, PrimaryButton, SecondaryButton, SectionTitle, Select, Skeleton, Textarea, useToast } from "@/components/ui";
import { AgentConfig, api, API_BASE, FeishuAgentBotConfig, FeishuChatDiagnoseItem, FeishuConfig } from "@/lib/api";
import { focusField } from "@/lib/form-feedback";

type ConfigForm = {
  appId: string;
  appSecret: string;
  verificationToken: string;
  botName: string;
  enabled: boolean;
};

type BotForm = {
  agent_id: string;
  app_id: string;
  app_secret: string;
  verification_token: string;
  bot_name: string;
  enabled: boolean;
  receive_enabled: boolean;
};

type TabKey = "global" | "agents" | "testing";

const emptyConfigForm: ConfigForm = {
  appId: "",
  appSecret: "",
  verificationToken: "",
  botName: "",
  enabled: true
};

const emptyBotForm: BotForm = {
  agent_id: "",
  app_id: "",
  app_secret: "",
  verification_token: "",
  bot_name: "",
  enabled: true,
  receive_enabled: false
};

const COMMANDS = ["#start 讨论主题", "开始讨论：讨论主题", "#ask Agent名称: 你的问题", "@Agent名称 你的问题", "暂停", "继续", "恢复", "停止"];
const TABS: Array<{ key: TabKey; label: string; desc: string }> = [
  { key: "global", label: "全局配置", desc: "Host Bot、Webhook 与命令说明" },
  { key: "agents", label: "Agent Bots", desc: "每个 Agent 的独立机器人身份" },
  { key: "testing", label: "测试诊断", desc: "发消息测试与 chat_id 诊断" }
];

function isTabKey(value: string | null): value is TabKey {
  return value === "global" || value === "agents" || value === "testing";
}

export default function FeishuExtensionPage() {
  const { toast } = useToast();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabKey>("global");

  const [configForm, setConfigForm] = useState<ConfigForm>(emptyConfigForm);
  const [botForm, setBotForm] = useState<BotForm>(emptyBotForm);
  const [config, setConfig] = useState<FeishuConfig | null>(null);
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [bots, setBots] = useState<FeishuAgentBotConfig[]>([]);
  const [testChatId, setTestChatId] = useState("");
  const [testText, setTestText] = useState("这是一条来自 AlignHub 的飞书测试消息。");
  const [testAgentId, setTestAgentId] = useState("");
  const [diagnoseChatId, setDiagnoseChatId] = useState("");
  const [diagnoseResults, setDiagnoseResults] = useState<FeishuChatDiagnoseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [savingBot, setSavingBot] = useState(false);
  const [testing, setTesting] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [busyAgentId, setBusyAgentId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const tab = new URLSearchParams(window.location.search).get("tab");
    if (isTabKey(tab)) {
      setActiveTab(tab);
    }
  }, []);

  const configErrors = useMemo(
    () => ({
      appId: configForm.appId.trim() ? "" : "请输入飞书 App ID",
      appSecret: configForm.appSecret.trim() ? "" : "请输入 App Secret",
      verificationToken: configForm.verificationToken.trim() ? "" : "请输入 Verification Token"
    }),
    [configForm]
  );

  const botErrors = useMemo(
    () => ({
      agent_id: botForm.agent_id ? "" : "请选择 Agent",
      app_id: botForm.app_id.trim() ? "" : "请输入飞书 Bot App ID",
      app_secret: botForm.app_secret.trim() ? "" : "请输入飞书 Bot App Secret",
      verification_token: botForm.verification_token.trim() ? "" : "请输入 Verification Token"
    }),
    [botForm]
  );

  const botMap = useMemo(() => Object.fromEntries(bots.map((bot) => [bot.agent_id, bot])), [bots]);

  async function loadAll(showLoader = false) {
    if (showLoader) setLoading(true);
    try {
      const [configData, agentData, botData] = await Promise.all([
        api.get<FeishuConfig>("/integrations/feishu/config"),
        api.get<AgentConfig[]>("/agents"),
        api.get<FeishuAgentBotConfig[]>("/integrations/feishu/agent-bots")
      ]);

      setConfig(configData);
      setAgents(agentData);
      setBots(botData);
      setConfigForm({
        appId: configData.app_id ?? "",
        appSecret: configData.app_secret ?? "",
        verificationToken: configData.verification_token ?? "",
        botName: configData.bot_name ?? "",
        enabled: configData.enabled ?? true
      });
      setBotForm((prev) => ({ ...prev, agent_id: prev.agent_id || agentData[0]?.id || "" }));
      setError("");
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "加载飞书集成数据失败";
      setError(nextError);
      toast({ tone: "danger", title: "加载失败", description: nextError });
    } finally {
      if (showLoader) setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll(true);
  }, []);

  function switchTab(tab: TabKey) {
    setActiveTab(tab);
    router.replace(`/extensions/feishu?tab=${tab}`, { scroll: false });
  }

  function resetBotForm() {
    setBotForm({ ...emptyBotForm, agent_id: agents[0]?.id || "" });
    setError("");
    setMessage("");
  }

  async function startEditBot(agentId: string) {
    setBusyAgentId(agentId);
    try {
      const bot = await api.get<FeishuAgentBotConfig>(`/agents/${agentId}/feishu-bot`);
      setBotForm({
        agent_id: agentId,
        app_id: bot.app_id ?? "",
        app_secret: bot.app_secret ?? "",
        verification_token: bot.verification_token ?? "",
        bot_name: bot.bot_name ?? "",
        enabled: Boolean(bot.enabled),
        receive_enabled: Boolean(bot.receive_enabled)
      });
      switchTab("agents");
      setError("");
      setMessage("");
      toast({ tone: "default", title: "已载入 Agent Bot 配置", description: `正在编辑 ${bot.agent_name ?? agentId}` });
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "读取 Agent Bot 配置失败";
      setError(nextError);
      toast({ tone: "danger", title: "读取配置失败", description: nextError });
    } finally {
      setBusyAgentId(null);
    }
  }

  async function saveConfig(event: React.FormEvent) {
    event.preventDefault();
    const firstError = Object.entries(configErrors).find(([, value]) => value)?.[0];
    if (firstError) {
      focusField(firstError);
      return;
    }

    setSavingConfig(true);
    setError("");
    setMessage("");
    try {
      await api.put("/integrations/feishu/config", {
        app_id: configForm.appId.trim(),
        app_secret: configForm.appSecret.trim(),
        verification_token: configForm.verificationToken.trim(),
        bot_name: configForm.botName.trim() || null,
        enabled: configForm.enabled
      });
      await loadAll();
      const successMessage = "飞书全局配置已保存。";
      setMessage(successMessage);
      toast({ tone: "success", title: "保存成功", description: successMessage });
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "保存飞书配置失败";
      setError(nextError);
      toast({ tone: "danger", title: "保存失败", description: nextError });
    } finally {
      setSavingConfig(false);
    }
  }

  async function saveBot(event: React.FormEvent) {
    event.preventDefault();
    const firstError = Object.entries(botErrors).find(([, value]) => value)?.[0];
    if (firstError) {
      focusField(firstError);
      return;
    }

    setSavingBot(true);
    setError("");
    setMessage("");
    try {
      await api.put<FeishuAgentBotConfig>(`/agents/${botForm.agent_id}/feishu-bot`, {
        app_id: botForm.app_id.trim(),
        app_secret: botForm.app_secret.trim(),
        verification_token: botForm.verification_token.trim(),
        bot_name: botForm.bot_name.trim() || null,
        enabled: botForm.enabled,
        receive_enabled: botForm.receive_enabled
      });
      await loadAll();
      const successMessage = "Agent Bot 配置已保存。";
      setMessage(successMessage);
      toast({ tone: "success", title: "保存成功", description: successMessage });
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "保存 Agent Bot 失败";
      setError(nextError);
      toast({ tone: "danger", title: "保存失败", description: nextError });
    } finally {
      setSavingBot(false);
    }
  }

  async function deleteBot(agentId: string) {
    setBusyAgentId(agentId);
    setError("");
    setMessage("");
    try {
      await api.del(`/agents/${agentId}/feishu-bot`);
      if (botForm.agent_id === agentId) resetBotForm();
      await loadAll();
      const successMessage = "已解绑飞书机器人。";
      setMessage(successMessage);
      toast({ tone: "success", title: "解绑成功", description: successMessage });
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "解绑失败";
      setError(nextError);
      toast({ tone: "danger", title: "解绑失败", description: nextError });
    } finally {
      setBusyAgentId(null);
    }
  }

  async function sendTest() {
    if (!testChatId.trim() || !testText.trim()) return;
    setTesting(true);
    setError("");
    setMessage("");
    try {
      await api.post("/integrations/feishu/test-send", {
        chat_id: testChatId.trim(),
        text: testText,
        agent_id: testAgentId || null
      });
      const successMessage = testAgentId ? "Agent Bot 测试消息已发送。" : "Host Bot 测试消息已发送。";
      setMessage(successMessage);
      toast({ tone: "success", title: "发送成功", description: successMessage });
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "发送测试消息失败";
      setError(nextError);
      toast({ tone: "danger", title: "发送失败", description: nextError });
    } finally {
      setTesting(false);
    }
  }

  async function diagnoseChat() {
    if (!diagnoseChatId.trim()) return;
    setDiagnosing(true);
    setError("");
    setMessage("");
    try {
      const result = await api.post<FeishuChatDiagnoseItem[]>("/integrations/feishu/diagnose-chat", {
        chat_id: diagnoseChatId.trim()
      });
      setDiagnoseResults(result);
      const successMessage = "chat_id 诊断完成。";
      setMessage(successMessage);
      toast({ tone: "success", title: "诊断完成", description: successMessage });
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "诊断失败";
      setDiagnoseResults([]);
      setError(nextError);
      toast({ tone: "danger", title: "诊断失败", description: nextError });
    } finally {
      setDiagnosing(false);
    }
  }

  const webhookPath = config?.webhook_path ?? "/api/v1/integrations/feishu/events";
  const webhookHint = `${API_BASE.replace("/api/v1", "")}${webhookPath}`;

  if (loading) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-[190px]" />
        <Skeleton className="h-[84px]" />
        <Skeleton className="h-[860px]" />
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="Feishu Center" title="飞书集成中心" desc="把 Host Bot、Agent Bot、测试发信与诊断能力统一收敛到一个入口，降低配置与排障的认知成本。" />
        <div className="flex flex-wrap gap-2">
          <Badge tone={config?.enabled ? "success" : "warn"}>{config?.enabled ? "全局集成已启用" : "全局集成未启用"}</Badge>
          <Badge tone="success">{bots.filter((bot) => bot.enabled).length} 个 Agent Bot 已启用</Badge>
          <Badge>{agents.length} 个 Agent</Badge>
          <Badge>Webhook 已就绪</Badge>
        </div>
      </Card>

      {error ? <InlineAlert tone="danger" title="飞书集成中心有一项操作失败" description={error} /> : null}
      {message ? <InlineAlert tone="success" title="操作成功" description={message} /> : null}

      <Card>
        <div className="grid gap-3 md:grid-cols-3">
          {TABS.map((tab) => {
            const active = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => switchTab(tab.key)}
                className={`rounded-[24px] border px-4 py-4 text-left transition ${
                  active ? "border-[var(--brand-strong)] bg-[var(--brand-soft)] shadow-[0_18px_40px_rgba(79,124,255,0.16)]" : "bg-[var(--panel-2)] hover:border-[var(--brand)]"
                }`}
              >
                <div className={`text-sm font-semibold ${active ? "text-[var(--brand-strong)]" : "text-[var(--text)]"}`}>{tab.label}</div>
                <div className="mt-1 text-sm leading-6 text-[var(--muted)]">{tab.desc}</div>
              </button>
            );
          })}
        </div>
      </Card>

      {activeTab === "global" ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)]">
          <Card>
            <SectionTitle eyebrow="Host Bot" title="全局配置" desc="Host Bot 负责统一接收群事件，由后端编排多 Agent 协同流程。" />
            <form onSubmit={saveConfig} className="space-y-4">
              <Field label="飞书 App ID" required error={configErrors.appId}>
                <Input name="appId" value={configForm.appId} invalid={Boolean(configErrors.appId)} onChange={(e) => setConfigForm((prev) => ({ ...prev, appId: e.target.value }))} placeholder="输入飞书 App ID" />
              </Field>
              <Field label="机器人显示名">
                <Input value={configForm.botName} onChange={(e) => setConfigForm((prev) => ({ ...prev, botName: e.target.value }))} placeholder="可选：Host Bot 显示名" />
              </Field>
              <Field label="App Secret" required error={configErrors.appSecret}>
                <Input name="appSecret" type="password" value={configForm.appSecret} invalid={Boolean(configErrors.appSecret)} onChange={(e) => setConfigForm((prev) => ({ ...prev, appSecret: e.target.value }))} placeholder="输入 App Secret" />
              </Field>
              <Field label="Verification Token" required error={configErrors.verificationToken}>
                <Input name="verificationToken" value={configForm.verificationToken} invalid={Boolean(configErrors.verificationToken)} onChange={(e) => setConfigForm((prev) => ({ ...prev, verificationToken: e.target.value }))} placeholder="输入 Verification Token" />
              </Field>
              <CheckboxRow checked={configForm.enabled} onChange={(checked) => setConfigForm((prev) => ({ ...prev, enabled: checked }))} label="启用飞书集成" description="启用后，群聊命令和回调事件会进入 AlignHub 的讨论编排流程。" />
              <div className="flex flex-wrap gap-3">
                <PrimaryButton type="submit" loading={savingConfig}>
                  保存全局配置
                </PrimaryButton>
                <SecondaryButton type="button" onClick={() => void loadAll()}>
                  刷新数据
                </SecondaryButton>
              </div>
            </form>
          </Card>

          <div className="grid gap-6">
            <Card>
              <SectionTitle eyebrow="Webhook" title="回调配置" desc="把飞书事件订阅接到当前后端即可开始处理群聊事件。" />
              <div className="flex flex-wrap gap-2">
                <Badge>{webhookPath}</Badge>
                <Badge tone="success">事件回调入口</Badge>
              </div>
              <p className="mt-3 break-all text-sm leading-7 text-[var(--muted)]">如果当前后端可被公网访问，请在飞书事件订阅中把请求地址配置为：{webhookHint}</p>
              <div className="mt-4 rounded-[22px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm leading-7 text-[var(--muted)]">Host Bot 负责统一接收群事件；独立 Agent Bot 发言身份在“Agent Bots”标签页维护。</div>
            </Card>

            <Card>
              <SectionTitle eyebrow="Command Guide" title="群内命令说明" desc="推荐使用明确命令，而不是依赖复杂的 @ 语义，提升协同的可预期性。" />
              <div className="grid gap-2">
                {COMMANDS.map((command) => (
                  <div key={command} className="rounded-[20px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)]">
                    {command}
                  </div>
                ))}
              </div>
              <div className="mt-4 rounded-[22px] border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm leading-7 text-[var(--muted)]">建议先在“讨论会话”页面创建会话，再通过飞书命令或 chat_id 绑定触发讨论。</div>
            </Card>
          </div>
        </div>
      ) : null}

      {activeTab === "agents" ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.95fr)]">
          <Card>
            <SectionTitle eyebrow="Bindings" title="Agent Bot 列表" desc="快速识别哪些 Agent 已完成机器人绑定，哪些角色仍待配置。" />
            <div className="grid gap-3">
              {agents.map((agent) => {
                const bot = botMap[agent.id];
                return (
                  <div key={agent.id} className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start gap-3">
                          <AgentAvatar seed={agent.id} name={agent.name} className="h-11 w-11" />
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-lg font-semibold text-[var(--text)]">{agent.name}</div>
                            <div className="truncate text-sm text-[var(--brand-strong)]">{agent.role}</div>
                          </div>
                        </div>
                        <div className="mt-3 grid gap-1 text-sm text-[var(--muted)]">
                          <div>机器人名称：{bot?.bot_name ?? "未配置"}</div>
                          <div>App ID：{bot?.app_id ?? "-"}</div>
                          <div>状态：{bot?.enabled ? "已启用" : "未启用"}</div>
                          <div>接收事件：{bot?.receive_enabled ? "开启" : "关闭"}</div>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <PrimaryButton type="button" loading={busyAgentId === agent.id} onClick={() => void startEditBot(agent.id)}>
                          {bot ? "编辑" : "配置"}
                        </PrimaryButton>
                        {bot ? (
                          <SecondaryButton
                            type="button"
                            loading={busyAgentId === agent.id}
                            onClick={() => {
                              if (!window.confirm(`确认解绑 Agent “${agent.name}” 的飞书机器人吗？`)) return;
                              void deleteBot(agent.id);
                            }}
                          >
                            解绑
                          </SecondaryButton>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })}
              {!agents.length ? <EmptyState title="当前没有 Agent" description="请先在 Agent 管理页面创建角色，再回来绑定独立 Bot。" /> : null}
            </div>
          </Card>

          <Card>
            <SectionTitle eyebrow="Configure" title="配置 Agent Bot" desc="为指定 Agent 绑定独立飞书机器人，用于角色化发言或接收事件。" />
            <form onSubmit={saveBot} className="space-y-4">
              <Field label="选择 Agent" required error={botErrors.agent_id}>
                <Select name="agent_id" value={botForm.agent_id} invalid={Boolean(botErrors.agent_id)} onChange={(e) => setBotForm((prev) => ({ ...prev, agent_id: e.target.value }))}>
                  <option value="">选择 Agent</option>
                  {agents.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="飞书 Bot App ID" required error={botErrors.app_id}>
                <Input name="app_id" value={botForm.app_id} invalid={Boolean(botErrors.app_id)} onChange={(e) => setBotForm((prev) => ({ ...prev, app_id: e.target.value }))} placeholder="输入 App ID" />
              </Field>
              <Field label="机器人显示名">
                <Input value={botForm.bot_name} onChange={(e) => setBotForm((prev) => ({ ...prev, bot_name: e.target.value }))} placeholder="可选：飞书显示名" />
              </Field>
              <Field label="飞书 Bot App Secret" required error={botErrors.app_secret}>
                <Input name="app_secret" type="password" value={botForm.app_secret} invalid={Boolean(botErrors.app_secret)} onChange={(e) => setBotForm((prev) => ({ ...prev, app_secret: e.target.value }))} placeholder="输入 App Secret" />
              </Field>
              <Field label="Verification Token" required error={botErrors.verification_token}>
                <Input name="verification_token" value={botForm.verification_token} invalid={Boolean(botErrors.verification_token)} onChange={(e) => setBotForm((prev) => ({ ...prev, verification_token: e.target.value }))} placeholder="输入 Verification Token" />
              </Field>
              <CheckboxRow checked={botForm.enabled} onChange={(checked) => setBotForm((prev) => ({ ...prev, enabled: checked }))} label="启用该 Agent Bot" description="启用后，角色可以用飞书机器人身份发送消息。" />
              <CheckboxRow checked={botForm.receive_enabled} onChange={(checked) => setBotForm((prev) => ({ ...prev, receive_enabled: checked }))} label="允许该 Agent Bot 直接接收飞书事件" description="适用于需要 Bot 直接监听群聊或话题消息的场景。" />
              <div className="flex flex-wrap gap-3">
                <PrimaryButton type="submit" loading={savingBot}>
                  保存 Agent Bot
                </PrimaryButton>
                <SecondaryButton type="button" onClick={resetBotForm}>
                  重置表单
                </SecondaryButton>
              </div>
            </form>
          </Card>
        </div>
      ) : null}

      {activeTab === "testing" ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)]">
          <Card>
            <SectionTitle eyebrow="Test Send" title="发送测试消息" desc="可选择 Host Bot 或某个 Agent Bot 身份，验证发消息能力是否正常。" />
            <div className="space-y-4">
              <Field label="目标 chat_id">
                <Input value={testChatId} onChange={(e) => setTestChatId(e.target.value)} placeholder="输入目标 chat_id" />
              </Field>
              <Field label="发送身份">
                <Select value={testAgentId} onChange={(e) => setTestAgentId(e.target.value)}>
                  <option value="">使用 Host Bot 发送</option>
                  {agents.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                      {agent.feishu_bot_name ? `（${agent.feishu_bot_name}）` : ""}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="消息内容">
                <Textarea value={testText} onChange={(e) => setTestText(e.target.value)} placeholder="输入测试消息内容" />
              </Field>
              <PrimaryButton type="button" loading={testing} disabled={!testChatId.trim() || !testText.trim()} onClick={sendTest}>
                发送测试消息
              </PrimaryButton>
            </div>
          </Card>

          <div className="grid gap-6">
            <Card>
              <SectionTitle eyebrow="Diagnosis" title="诊断 chat_id" desc="检查每个 Agent Bot 是否被飞书识别在目标群内，便于排查“能发消息但群内不可见”等问题。" />
              <div className="space-y-4">
                <Field label="待诊断 chat_id">
                  <Input value={diagnoseChatId} onChange={(e) => setDiagnoseChatId(e.target.value)} placeholder="输入 chat_id" />
                </Field>
                <PrimaryButton type="button" loading={diagnosing} disabled={!diagnoseChatId.trim()} onClick={diagnoseChat}>
                  诊断 chat_id
                </PrimaryButton>
                {diagnoseResults.length ? (
                  <div className="grid gap-2">
                    {diagnoseResults.map((item) => (
                      <div key={item.agent_id} className="rounded-[22px] border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-sm text-[var(--text)]">
                        <div className="font-medium">
                          {item.agent_name}
                          {item.bot_name ? `（${item.bot_name}）` : ""}
                        </div>
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
                ) : (
                  <EmptyState title="还没有诊断结果" description="输入 chat_id 后点击诊断，这里会列出每个 Agent Bot 在目标群内的识别结果。" />
                )}
              </div>
            </Card>

            <Card>
              <SectionTitle eyebrow="Tips" title="排障建议" desc="合并后常用的测试和诊断动作都收敛在这里。" />
              <div className="rounded-[22px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm leading-7 text-[var(--muted)]">
                建议顺序：先确认“全局配置”可用 → 再到“Agent Bots”绑定角色身份 → 最后在本标签页做发信测试与 chat_id 诊断。
              </div>
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  );
}

