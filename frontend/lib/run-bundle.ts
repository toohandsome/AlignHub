"use client";

import { useEffect, useState } from "react";

import { AgentConfig, api, ChatSession, DiscussionEvent, DiscussionRun, FinalReport, ModelConfig, ToolCallLog } from "@/lib/api";

/**
 * 兼容新旧两种事件载荷字段。
 * 后端逐步统一到 payload，但历史数据里可能仍是 payload_json。
 */
export function normalizePayload(event: DiscussionEvent): Record<string, unknown> {
  return event.payload ?? event.payload_json ?? {};
}

/**
 * 统一日期时间展示格式，缺失时返回占位符。
 */
export function formatDateTime(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

/**
 * 聚合 Run 详情页 / 回放页所需的全部基础数据。
 * 这样两个页面共享同一套加载逻辑，避免重复请求与状态结构分叉。
 */
export function useRunBundle(runId?: string) {
  const [run, setRun] = useState<DiscussionRun | null>(null);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [events, setEvents] = useState<DiscussionEvent[]>([]);
  const [toolLogs, setToolLogs] = useState<ToolCallLog[]>([]);
  const [report, setReport] = useState<FinalReport | null>(null);
  const [error, setError] = useState("");

  /**
   * 并行加载 Run 相关的静态快照。
   * 先查 run，再根据其中的 session_id 拉取会话信息。
   */
  async function loadBundle(targetRunId: string) {
    const runData = await api.get<DiscussionRun>(`/runs/${targetRunId}`);
    const [eventData, toolData, sessionData, agentData, modelData] = await Promise.all([
      api.get<DiscussionEvent[]>(`/runs/${targetRunId}/events`),
      api.get<ToolCallLog[]>(`/runs/${targetRunId}/tool-logs`),
      api.get<ChatSession>(`/chat-sessions/${runData.session_id}`),
      api.get<AgentConfig[]>("/agents"),
      api.get<ModelConfig[]>("/models")
    ]);

    setRun(runData);
    setEvents(eventData);
    setToolLogs(toolData);
    setSession(sessionData);
    setAgents(agentData);
    setModels(modelData);

    // 报告只在 run 结束或生成后才存在，因此单独容错，不影响主页面渲染。
    try {
      const reportData = await api.get<FinalReport>(`/runs/${targetRunId}/report`);
      setReport(reportData);
    } catch {
      setReport(null);
    }
  }

  useEffect(() => {
    if (!runId) return;
    let mounted = true;

    // runId 变化时重新加载一整套页面上下文。
    (async () => {
      try {
        await loadBundle(runId);
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "加载运行数据失败");
        }
      }
    })();

    return () => {
      mounted = false;
    };
  }, [runId]);

  return {
    run,
    setRun,
    session,
    setSession,
    agents,
    setAgents,
    models,
    setModels,
    events,
    setEvents,
    toolLogs,
    setToolLogs,
    report,
    setReport,
    error,
    setError,
    reload: runId ? () => loadBundle(runId) : undefined
  };
}
