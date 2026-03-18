"use client";

import { PropsWithChildren } from "react";

import { EventFilterKey, EVENT_FILTER_OPTIONS } from "@/lib/discussion";

/**
 * 根据稳定 seed 生成一个伪随机哈希值，
 * 用于保证同一 Agent 在不同页面的头像颜色保持一致。
 */
function hashSeed(seed: string): number {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }
  return hash;
}

const AVATAR_EMOJIS = ["🤖", "🧠", "🛰️", "🛠️", "📘", "⚙️", "🚀", "💡", "🧩", "🔍"];

/**
 * 为 Agent 生成轻量头像：
 * - 颜色由 seed 稳定决定
 * - emoji 用于快速区分不同角色
 */
export function AgentAvatar({ seed, name, className = "" }: { seed: string; name: string; className?: string }) {
  const hash = hashSeed(seed || name || "agent");
  const hueA = hash % 360;
  const hueB = (hash * 7) % 360;
  const emoji = AVATAR_EMOJIS[hash % AVATAR_EMOJIS.length];

  return (
    <div
      title={name}
      className={`flex shrink-0 items-center justify-center rounded-full text-base shadow-sm ${className}`}
      style={{
        background: `linear-gradient(135deg, hsl(${hueA} 80% 78%), hsl(${hueB} 70% 68%))`
      }}
    >
      <span>{emoji}</span>
    </div>
  );
}

/**
 * 时间线事件筛选面板。
 * 只负责展示选项与回调，不关心具体页面状态管理。
 */
export function EventFilterPanel({
  selected,
  onToggle
}: {
  selected: EventFilterKey[];
  onToggle: (key: EventFilterKey) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {EVENT_FILTER_OPTIONS.map((item) => {
        const active = selected.includes(item.key);
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onToggle(item.key)}
            className={`rounded-full border px-3 py-1.5 text-sm transition ${
              active
                ? "border-sky-400 bg-sky-500/10 text-sky-500"
                : "border-[var(--line)] bg-[var(--panel-2)] text-[var(--muted)] hover:border-sky-400"
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * JSON 详情折叠区。
 * 用于统一展示事件 / 工具日志的结构化载荷。
 */
export function JsonDetails({
  expanded,
  onToggle,
  payload,
  className = ""
}: {
  expanded: boolean;
  onToggle: () => void;
  payload: Record<string, unknown>;
  className?: string;
}) {
  return (
    <div className={`mt-3 ${className}`}>
      <button
        type="button"
        onClick={onToggle}
        className="text-xs text-sky-500 transition hover:text-sky-400"
      >
        {expanded ? "收起详情" : "展开详情"}
      </button>
      {expanded ? (
        <pre className="mt-2 overflow-x-auto rounded-xl bg-[var(--panel)] p-3 text-xs text-[var(--muted)]">
          {JSON.stringify(payload, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

/**
 * 通用胶囊标签容器，常用于展示 Agent / Tool / Skill / MCP 标签。
 */
export function AgentChip({ children, className = "" }: PropsWithChildren<{ className?: string }>) {
  return (
    <div
      className={`inline-flex min-w-0 items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)] ${className}`}
    >
      {children}
    </div>
  );
}
