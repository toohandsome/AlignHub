"use client";

import { PropsWithChildren } from "react";

import { EventFilterKey, EVENT_FILTER_OPTIONS } from "@/lib/discussion";

function hashSeed(seed: string): number {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }
  return hash;
}

const AVATAR_EMOJIS = ["🧠", "🛰️", "🛠️", "📌", "🧭", "⚙️", "📎", "🔍", "🧪", "📝"];

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
        background: `linear-gradient(135deg, hsl(${hueA} 85% 76%), hsl(${hueB} 72% 66%))`
      }}
    >
      <span>{emoji}</span>
    </div>
  );
}

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
                ? "border-[var(--brand-strong)] bg-[var(--brand-soft)] text-[var(--brand-strong)]"
                : "border-[var(--line)] bg-[var(--panel-2)] text-[var(--muted)] hover:border-[var(--brand)]"
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

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
      <button type="button" onClick={onToggle} className="text-xs font-medium text-[var(--brand-strong)] transition hover:opacity-80">
        {expanded ? "收起详情" : "展开详情"}
      </button>
      {expanded ? <pre className="mt-2 overflow-x-auto rounded-2xl bg-[var(--panel-3)] p-3 text-xs text-[var(--muted)]">{JSON.stringify(payload, null, 2)}</pre> : null}
    </div>
  );
}

export function AgentChip({ children, className = "" }: PropsWithChildren<{ className?: string }>) {
  return <div className={`inline-flex min-w-0 items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)] ${className}`}>{children}</div>;
}
