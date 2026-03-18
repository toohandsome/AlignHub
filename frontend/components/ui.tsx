"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  PropsWithChildren,
  SelectHTMLAttributes,
  TextareaHTMLAttributes
} from "react";

import { useTheme } from "@/components/theme-provider";

/**
 * 页面最外层布局容器，统一控制内容区最大宽度和边距。
 */
export function Shell({ children }: PropsWithChildren) {
  return (
    <div className="mx-auto min-h-screen w-full max-w-[1600px] overflow-x-hidden px-4 py-4 md:px-6 lg:px-8">
      {children}
    </div>
  );
}

/**
 * 左侧导航栏。
 * 这里统一维护管理台核心页面入口与激活态样式。
 */
export function Nav() {
  const pathname = usePathname();
  const items = [
    { href: "/", label: "总览" },
    { href: "/providers", label: "Provider / Model" },
    { href: "/skills", label: "Skill 管理" },
    { href: "/mcps", label: "MCP 管理" },
    { href: "/agents", label: "Agent 管理" },
    { href: "/sessions", label: "讨论会话" },
    { href: "/history", label: "历史会话" },
    { href: "/extensions/feishu", label: "飞书集成" },
    { href: "/extensions/feishu/bots", label: "飞书机器人" }
  ];

  return (
    <aside className="surface flex h-full min-w-0 flex-col rounded-3xl border p-4 lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)]">
      <div>
        <div className="text-xl font-semibold text-[var(--text)]">AlignHub</div>
        <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
          面向多智能体协同、共识收敛与联合决策的运行平台。
        </p>
      </div>

      <nav className="mt-6 grid gap-2">
        {items.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-2xl border px-4 py-3 text-sm transition ${
                active
                  ? "border-sky-400 bg-sky-500/10 text-sky-500"
                  : "surface-muted hover:border-sky-400 hover:text-sky-500"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto pt-4">
        <ThemeToggle />
      </div>
    </aside>
  );
}

/**
 * 通用卡片容器。
 */
export function Card({ children, className = "" }: PropsWithChildren<{ className?: string }>) {
  return <div className={`surface min-w-0 overflow-hidden rounded-2xl border p-4 ${className}`}>{children}</div>;
}

/**
 * 统一的区块标题组件。
 */
export function SectionTitle({ title, desc }: { title: string; desc?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-xl font-semibold text-[var(--text)]">{title}</h2>
      {desc ? <p className="mt-1 text-sm text-[var(--muted)]">{desc}</p> : null}
    </div>
  );
}

/**
 * 统一状态徽标。
 */
export function Badge({
  children,
  tone = "default"
}: PropsWithChildren<{ tone?: "default" | "success" | "warn" | "danger" }>) {
  const toneClass =
    tone === "success"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500 dark:text-emerald-300"
      : tone === "warn"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-300"
        : tone === "danger"
          ? "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-300"
          : "border-[var(--line)] bg-[var(--panel-2)] text-[var(--muted)]";

  return <span className={`inline-flex rounded-full border px-2 py-1 text-xs ${toneClass}`}>{children}</span>;
}

/**
 * 主按钮，用于提交、启动等主操作。
 */
export function PrimaryButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded-xl bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50 ${props.className ?? ""}`}
    />
  );
}

/**
 * 次按钮，用于刷新、取消、删除等辅助操作。
 */
export function SecondaryButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] transition hover:border-sky-400 disabled:cursor-not-allowed disabled:opacity-50 ${props.className ?? ""}`}
    />
  );
}

/**
 * 统一输入框样式。
 */
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-sky-400 ${props.className ?? ""}`}
    />
  );
}

/**
 * 统一下拉框样式。
 */
export function Select(props: PropsWithChildren<SelectHTMLAttributes<HTMLSelectElement>>) {
  return (
    <select
      {...props}
      className={`w-full rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-sky-400 ${props.className ?? ""}`}
    >
      {props.children}
    </select>
  );
}

/**
 * 统一多行输入框样式。
 */
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`min-h-24 w-full rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-sky-400 ${props.className ?? ""}`}
    />
  );
}

/**
 * 主题切换按钮。
 */
function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      className="w-full rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400"
      type="button"
    >
      {theme === "light" ? "切换深色" : "切换浅色"}
    </button>
  );
}
