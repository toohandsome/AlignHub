"use client";

import { useEffect, useState } from "react";

import { AgentConfig, api, ChatSession, DiscussionEvent, DiscussionRun, FinalReport, ModelConfig, ToolCallLog } from "@/lib/api";

export function normalizePayload(event: DiscussionEvent): Record<string, unknown> {
  return event.payload ?? event.payload_json ?? {};
}

export function formatDateTime(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

export function useRunBundle(runId?: string) {
  const [run, setRun] = useState<DiscussionRun | null>(null);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [events, setEvents] = useState<DiscussionEvent[]>([]);
  const [toolLogs, setToolLogs] = useState<ToolCallLog[]>([]);
  const [report, setReport] = useState<FinalReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function loadBundle(targetRunId: string) {
    setLoading(true);
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
    setError("");

    try {
      const reportData = await api.get<FinalReport>(`/runs/${targetRunId}/report`);
      setReport(reportData);
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!runId) return;
    let mounted = true;

    (async () => {
      try {
        await loadBundle(runId);
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "加载运行数据失败");
          setLoading(false);
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
    loading,
    reload: runId ? () => loadBundle(runId) : undefined
  };
}
