"use client";

import { Badge } from "@/components/ui";

type ConflictDetail = Record<string, unknown>;

function textOf(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function labelForField(field: string): string {
  const mapping: Record<string, string> = {
    agreements: "共识",
    open_questions: "开放问题",
    candidate_options: "候选方案",
    risks: "风险",
    next_focus: "下一步焦点",
    recent_key_points: "关键点"
  };
  return mapping[field] ?? (field || "未知字段");
}

function labelForOperation(operation: string): string {
  const mapping: Record<string, string> = {
    add: "新增",
    replace: "替换",
    remove: "移除",
    close: "关闭",
    reopen: "重新打开"
  };
  return mapping[operation] ?? (operation || "未知操作");
}

function toneForStatus(status: string): "default" | "success" | "warn" | "danger" {
  if (status === "unresolved_conflict") return "danger";
  if (status === "conflicted") return "warn";
  if (status === "resolved") return "success";
  return "default";
}

function FieldRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="grid gap-1 sm:grid-cols-[108px_minmax(0,1fr)] sm:gap-3">
      <div className="text-xs text-[var(--muted)]">{label}</div>
      <div className="text-sm leading-6 text-[var(--text)]">{value}</div>
    </div>
  );
}

export function UnresolvedConflictCard({
  detail,
  fallbackSummary
}: {
  detail: ConflictDetail;
  fallbackSummary?: string;
}) {
  const summary = textOf(detail.summary) || fallbackSummary || "未解决冲突";
  const agentName = textOf(detail.agent_name) || textOf(detail.agent_id) || "未知 Agent";
  const targetField = textOf(detail.target_field);
  const operation = textOf(detail.operation);
  const value = textOf(detail.value);
  const reason = textOf(detail.reason);
  const status = textOf(detail.status) || "unresolved_conflict";
  const roundNo = detail.round_no;

  return (
    <details className="rounded-[24px] border border-rose-500/20 bg-rose-500/10 px-4 py-4 transition hover:border-rose-500/35">
      <summary className="cursor-pointer list-none">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-[var(--text)]">{summary}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge tone={toneForStatus(status)}>{status}</Badge>
              <Badge>{agentName}</Badge>
              {targetField ? <Badge>{labelForField(targetField)}</Badge> : null}
              {operation ? <Badge tone="warn">{labelForOperation(operation)}</Badge> : null}
              {typeof roundNo === "number" || typeof roundNo === "string" ? <Badge>第 {String(roundNo)} 轮</Badge> : null}
            </div>
          </div>
          <div className="text-xs font-medium text-rose-500">展开详情</div>
        </div>
      </summary>

      <div className="mt-4 space-y-3 rounded-[22px] bg-[var(--panel)] p-4">
        <FieldRow label="冲突主张" value={value} />
        <FieldRow label="涉及字段" value={targetField ? labelForField(targetField) : ""} />
        <FieldRow label="变更类型" value={operation ? labelForOperation(operation) : ""} />
        <FieldRow label="提出者" value={agentName} />
        <FieldRow label="所在轮次" value={typeof roundNo === "number" || typeof roundNo === "string" ? `第 ${String(roundNo)} 轮` : ""} />
        <FieldRow label="挂起原因" value={reason || "主持人尚未给出足够明确的裁决，已挂起等待后续轮次继续处理。"} />

        <details className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-3">
          <summary className="cursor-pointer text-xs text-[var(--muted)]">查看原始结构化数据</summary>
          <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(detail, null, 2)}</pre>
        </details>
      </div>
    </details>
  );
}
