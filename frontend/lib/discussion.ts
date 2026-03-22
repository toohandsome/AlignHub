import { AgentConfig, DiscussionEvent, ModelConfig } from "@/lib/api";

export type EventFilterKey = "message" | "tool" | "status" | "report";

export const EVENT_FILTER_OPTIONS: Array<{ key: EventFilterKey; label: string }> = [
  { key: "message", label: "发言" },
  { key: "tool", label: "工具" },
  { key: "status", label: "状态" },
  { key: "report", label: "报告" }
];

export const ALL_EVENT_FILTER_KEYS: EventFilterKey[] = EVENT_FILTER_OPTIONS.map((item) => item.key);

export type AgentDirectory = Record<
  string,
  {
    id: string;
    name: string;
    modelName?: string;
    label: string;
  }
>;

export function buildAgentDirectory(agents: AgentConfig[], models: ModelConfig[]): AgentDirectory {
  const modelMap = Object.fromEntries(models.map((model) => [model.id, model]));

  return Object.fromEntries(
    agents.map((agent) => {
      const modelName = modelMap[agent.model_id]?.model_name;
      return [
        agent.id,
        {
          id: agent.id,
          name: agent.name,
          modelName,
          label: modelName ? `${agent.name}（${modelName}）` : agent.name
        }
      ];
    })
  );
}

export function categorizeEventType(eventType: string): EventFilterKey {
  if (eventType === "message_completed" || eventType === "user_input") return "message";
  if (eventType.startsWith("tool_")) return "tool";
  if (eventType === "report_generated") return "report";
  return "status";
}

export function isEventVisible(eventType: string, selectedFilters: EventFilterKey[]): boolean {
  return selectedFilters.includes(categorizeEventType(eventType));
}

export function eventTypeLabel(eventType: string): string {
  switch (eventType) {
    case "message_completed":
      return "发言";
    case "user_input":
      return "用户补充";
    case "tool_started":
      return "工具开始";
    case "tool_completed":
      return "工具完成";
    case "tool_failed":
      return "工具失败";
    case "run_status":
      return "运行状态";
    case "report_generated":
      return "报告生成";
    case "error":
      return "错误";
    default:
      return eventType;
  }
}

export function summarizeEvent(event: {
  event_type: string;
  payload: Record<string, unknown>;
  tool_name?: string | null;
  round_no: number;
}): string {
  const payload = event.payload ?? {};
  const metadata = typeof payload.metadata === "object" && payload.metadata !== null ? (payload.metadata as Record<string, unknown>) : {};

  switch (event.event_type) {
    case "message_completed":
      return String(payload.text ?? "");
    case "user_input": {
      const important = metadata.mark_important === true;
      return `${important ? "用户重点关注" : "用户补充"}：${String(payload.text ?? "")}`;
    }
    case "tool_started":
      return `开始调用 ${event.tool_name ?? "工具"}`;
    case "tool_completed":
      return `已完成 ${event.tool_name ?? "工具"}`;
    case "tool_failed":
      return `调用 ${event.tool_name ?? "工具"} 失败`;
    case "report_generated":
      return `已生成报告：${String(payload.title ?? "最终结论报告")}`;
    case "error":
      return String(payload.message ?? "运行出现错误");
    case "run_status": {
      const status = String(payload.status ?? "状态更新");
      const labelMap: Record<string, string> = {
        running: "运行中",
        paused: "已暂停",
        resumed: "已恢复",
        stopped: "已停止",
        finished: "已完成",
        round_started: "轮次开始",
        moderator_decision: "主持人裁决"
      };
      const display = labelMap[status] ?? status;
      const reason = payload.reason ? ` · ${String(payload.reason)}` : "";
      const nextFocus = payload.next_focus ? ` · 下一步：${String(payload.next_focus)}` : "";
      return `${display}${reason}${nextFocus}`;
    }
    default:
      return JSON.stringify(payload, null, 2);
  }
}

export function resolveAgentDisplay(
  directory: AgentDirectory,
  agentId?: string | null,
  fallbackName?: string | null
): {
  name: string;
  label: string;
  modelName?: string;
  seed: string;
} {
  const matched = agentId ? directory[agentId] : undefined;
  const name = matched?.name ?? fallbackName ?? "Agent";

  return {
    name,
    label: matched?.label ?? name,
    modelName: matched?.modelName,
    seed: agentId ?? name
  };
}

export function latestStructuredStatePreview(events: Array<DiscussionEvent & { payload?: Record<string, unknown> }>) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const payload = (events[index].payload ?? events[index].payload_json ?? {}) as Record<string, unknown>;
    const state = payload.structured_state;
    if (typeof state === "object" && state !== null) {
      return state as Record<string, unknown>;
    }
  }
  return null;
}
