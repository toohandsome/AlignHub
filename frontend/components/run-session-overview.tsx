"use client";

import { AgentChip, AgentAvatar } from "@/components/discussion-ui";
import { ChatSession } from "@/lib/api";
import { AgentDirectory } from "@/lib/discussion";

/**
 * 展示当前 Run 关联的会话概览信息。
 * 包括会话名称、讨论主题以及参与者列表。
 */
export function RunSessionOverview({
  session,
  participants
}: {
  session: ChatSession | null;
  participants: Array<AgentDirectory[string]>;
}) {
  return (
    <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
      <div className="text-xs text-[var(--muted)]">当前会话</div>
      <div className="mt-1 break-words text-lg font-medium text-[var(--text)]">{session?.name ?? "加载中..."}</div>
      <div className="mt-3 text-xs text-[var(--muted)]">讨论 Topic</div>
      <div className="mt-1 whitespace-pre-wrap break-words text-sm text-[var(--text)]">{session?.topic ?? "-"}</div>
      <div className="mt-4 flex flex-wrap gap-2">
        {participants.map((agent) => (
          <AgentChip key={agent.id}>
            <AgentAvatar seed={agent.id} name={agent.name} className="h-7 w-7" />
            <span className="truncate">{agent.label}</span>
          </AgentChip>
        ))}
        {!participants.length ? <span className="text-sm text-[var(--muted)]">暂无参与智能体</span> : null}
      </div>
    </div>
  );
}
