"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  PropsWithChildren,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState
} from "react";

import { useTheme } from "@/components/theme-provider";

type ToastTone = "default" | "success" | "warn" | "danger";

type ToastInput = {
  title: string;
  description?: string;
  tone?: ToastTone;
};

type ToastItem = ToastInput & { id: string };

type InputLikeProps<T> = T & {
  invalid?: boolean;
};

const NAV_ITEMS = [
  { href: "/", label: "总览", short: "Overview" },
  { href: "/providers", label: "Provider / Model", short: "LLM 配置" },
  { href: "/skills", label: "Skill 管理", short: "提示能力" },
  { href: "/mcps", label: "MCP 管理", short: "外部能力" },
  { href: "/agents", label: "Agent 管理", short: "角色编排" },
  { href: "/sessions", label: "讨论会话", short: "协同流程" },
  { href: "/history", label: "历史会话", short: "运行回放" },
  { href: "/extensions/feishu", label: "飞书集成", short: "渠道接入" }
];

const ToastContext = createContext<{
  toast: (input: ToastInput) => void;
}>({
  toast: () => undefined
});

function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function Spinner({ className = "" }: { className?: string }) {
  return <span className={cn("inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent", className)} aria-hidden="true" />;
}

export function ToastProvider({ children }: PropsWithChildren) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const toast = useCallback((input: ToastInput) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((prev) => [...prev, { ...input, id }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[80] flex w-[min(92vw,380px)] flex-col gap-3">
        {toasts.map((item) => (
          <div
            key={item.id}
            className={cn(
              "pointer-events-auto rounded-2xl border px-4 py-3 shadow-[0_24px_80px_rgba(15,23,42,0.22)] backdrop-blur-xl transition duration-300 toast-enter",
              item.tone === "success" && "border-emerald-400/30 bg-emerald-500/12 text-emerald-50 dark:text-emerald-100",
              item.tone === "warn" && "border-amber-400/30 bg-amber-500/12 text-amber-950 dark:text-amber-100",
              item.tone === "danger" && "border-rose-400/30 bg-rose-500/12 text-rose-50 dark:text-rose-100",
              (!item.tone || item.tone === "default") && "border-[var(--line-strong)] bg-[color:color-mix(in_srgb,var(--panel)_84%,transparent)] text-[var(--text)]"
            )}
          >
            <div className="flex items-start gap-3">
              <div className={cn("mt-0.5 h-2.5 w-2.5 rounded-full", item.tone === "success" ? "bg-emerald-400" : item.tone === "warn" ? "bg-amber-400" : item.tone === "danger" ? "bg-rose-400" : "bg-[var(--brand)]")} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{item.title}</div>
                {item.description ? <div className="mt-1 text-sm text-[var(--muted)] dark:text-white/75">{item.description}</div> : null}
              </div>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

export function Shell({ children }: PropsWithChildren) {
  return (
    <div className="relative min-h-screen w-full overflow-x-hidden">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-[-12rem] top-[-12rem] h-[28rem] w-[28rem] rounded-full bg-[radial-gradient(circle,rgba(79,124,255,0.16),transparent_62%)]" />
        <div className="absolute bottom-[-16rem] right-[-10rem] h-[32rem] w-[32rem] rounded-full bg-[radial-gradient(circle,rgba(124,58,237,0.14),transparent_60%)]" />
      </div>
      <div className="relative px-4 py-4 md:px-6 lg:px-0 lg:py-0">{children}</div>
    </div>
  );
}

export function Nav() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    const originalOverflow = document.body.style.overflow;
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [mobileOpen]);

  const brandBlock = (
    <div>
      {/* <div className="inline-flex items-center gap-2 rounded-full border border-[var(--line-strong)] bg-[var(--brand-soft)] px-3 py-1 text-xs font-medium text-[var(--brand-strong)]">
        Multi-Agent Workspace
      </div> */}
      <div className="mt-4 text-xl font-semibold tracking-tight text-[var(--text)]">AlignHub</div>
      <p className="mt-2 text-sm leading-6 text-[var(--muted)]">面向多智能体协同、共识收敛与联合决策的统一工作台。</p>
    </div>
  );

  return (
    <>
      <div className="surface sticky top-0 z-30 flex items-center justify-between rounded-2xl border px-4 py-3 lg:hidden">
        <div>
          <div className="text-sm font-semibold tracking-[0.18em] text-[var(--brand-strong)] uppercase">AlignHub</div>
          <div className="mt-1 text-xs text-[var(--muted)]">智能协同控制台</div>
        </div>
        <button type="button" onClick={() => setMobileOpen((value) => !value)} className="btn-secondary px-3 py-2 text-sm">
          {mobileOpen ? "关闭菜单" : "打开菜单"}
        </button>
      </div>

      {mobileOpen ? <button type="button" aria-label="关闭导航遮罩" onClick={() => setMobileOpen(false)} className="fixed inset-0 z-30 bg-slate-950/48 lg:hidden" /> : null}

      <aside
        className={cn(
          "surface fixed inset-y-0 left-0 z-40 flex w-[292px] min-w-0 flex-col border-r px-5 py-6 transition-transform duration-300 ease-out",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          "lg:translate-x-0 lg:left-0 lg:top-0 lg:z-20 lg:h-screen lg:rounded-none lg:border-b-0 lg:border-l-0 lg:border-t-0"
        )}
      >
        <div className="flex items-start justify-between gap-3">
          {brandBlock}
          <button type="button" onClick={() => setMobileOpen(false)} className="btn-secondary px-2.5 py-1.5 text-xs lg:hidden">
            关闭
          </button>
        </div>

        <nav className="mt-8 grid flex-1 content-start gap-2 overflow-y-auto pr-1">
          {NAV_ITEMS.map((item, index) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group rounded-2xl border px-4 py-3 transition duration-200",
                  active ? "border-[var(--brand-strong)] bg-[var(--brand-soft)] text-[var(--brand-strong)] shadow-[0_14px_40px_rgba(79,124,255,0.18)]" : "surface-muted hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">{item.label}</div>
                    <div className="mt-1 text-xs text-[var(--muted)] group-hover:text-[var(--brand-strong)]">{item.short}</div>
                  </div>
                  <span className="rounded-full border border-[var(--line)] px-2 py-1 text-[11px] text-[var(--muted)]">0{index + 1}</span>
                </div>
              </Link>
            );
          })}
        </nav>

        {/* <div className="mt-auto space-y-3 pt-4">
          <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--muted)]">
            <div className="font-medium text-[var(--text)]">当前工作流</div>
            <div className="mt-1">配置模型 → 编排 Agent → 创建讨论 → 跟踪运行回放</div>
          </div>
          <ThemeToggle />
        </div> */}
      </aside>
    </>
  );
}

export function Card({ children, className = "" }: PropsWithChildren<{ className?: string }>) {
  return <div className={cn("surface min-w-0 overflow-hidden rounded-[28px] border p-5 md:p-6", className)}>{children}</div>;
}

export function SectionTitle({ title, desc, eyebrow, actions }: { title: string; desc?: string; eyebrow?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        {eyebrow ? <div className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--brand-strong)]">{eyebrow}</div> : null}
        <h2 className="mt-1 text-xl font-semibold tracking-tight text-[var(--text)] md:text-2xl">{title}</h2>
        {desc ? <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">{desc}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

export function InlineAlert({ tone = "default", title, description, className = "" }: { tone?: ToastTone; title: string; description?: string; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3 text-sm",
        tone === "success" && "border-emerald-400/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
        tone === "warn" && "border-amber-400/30 bg-amber-500/10 text-amber-700 dark:text-amber-200",
        tone === "danger" && "border-rose-400/30 bg-rose-500/10 text-rose-700 dark:text-rose-200",
        tone === "default" && "border-[var(--line)] bg-[var(--panel-2)] text-[var(--text)]",
        className
      )}
    >
      <div className="font-medium">{title}</div>
      {description ? <div className="mt-1 text-[var(--muted)] dark:text-white/70">{description}</div> : null}
    </div>
  );
}

export function Badge({ children, tone = "default" }: PropsWithChildren<{ tone?: ToastTone }>) {
  const toneClass =
    tone === "success"
      ? "border-emerald-500/35 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300"
      : tone === "warn"
        ? "border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-300"
        : tone === "danger"
          ? "border-rose-500/35 bg-rose-500/10 text-rose-600 dark:text-rose-300"
          : "border-[var(--line)] bg-[var(--panel-2)] text-[var(--muted)]";

  return <span className={cn("inline-flex rounded-full border px-2.5 py-1 text-xs font-medium", toneClass)}>{children}</span>;
}

function ButtonBase({ tone, loading, className, children, disabled, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { tone: "primary" | "secondary"; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-2xl px-4 py-2.5 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2 focus-visible:ring-offset-transparent disabled:cursor-not-allowed disabled:opacity-55",
        tone === "primary" ? "btn-primary" : "btn-secondary",
        className
      )}
    >
      {loading ? <Spinner /> : null}
      <span>{children}</span>
    </button>
  );
}

export function PrimaryButton(props: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return <ButtonBase {...props} tone="primary" />;
}

export function SecondaryButton(props: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return <ButtonBase {...props} tone="secondary" />;
}

export function Input({ invalid, className, ...props }: InputLikeProps<InputHTMLAttributes<HTMLInputElement>>) {
  return <input {...props} aria-invalid={invalid || undefined} data-invalid={invalid || undefined} className={cn("field-base", invalid && "field-invalid", className)} />;
}

export function Select({ invalid, className, children, ...props }: PropsWithChildren<InputLikeProps<SelectHTMLAttributes<HTMLSelectElement>>>) {
  return (
    <select {...props} aria-invalid={invalid || undefined} data-invalid={invalid || undefined} className={cn("field-base", invalid && "field-invalid", className)}>
      {children}
    </select>
  );
}

export function Textarea({ invalid, className, ...props }: InputLikeProps<TextareaHTMLAttributes<HTMLTextAreaElement>>) {
  return <textarea {...props} aria-invalid={invalid || undefined} data-invalid={invalid || undefined} className={cn("field-base min-h-28", invalid && "field-invalid", className)} />;
}

export function Field({ label, hint, error, required, children }: PropsWithChildren<{ label: string; hint?: string; error?: string; required?: boolean }>) {
  return (
    <label className="grid gap-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-[var(--text)]">
          {label}
          {required ? <span className="ml-1 text-rose-500">*</span> : null}
        </span>
        {hint ? <span className="text-xs text-[var(--muted)]">{hint}</span> : null}
      </div>
      {children}
      {error ? <p className="text-sm text-rose-500">{error}</p> : null}
    </label>
  );
}

export function CheckboxRow({ checked, onChange, label, description, badge }: { checked: boolean; onChange: (checked: boolean) => void; label: string; description?: string; badge?: React.ReactNode }) {
  return (
    <label className="flex items-start gap-3 rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 transition hover:border-[var(--brand)]/50">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="mt-1 h-4 w-4 rounded border-[var(--line)] text-[var(--brand-strong)]" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-[var(--text)]">
          <span>{label}</span>
          {badge}
        </div>
        {description ? <div className="mt-1 text-sm leading-6 text-[var(--muted)]">{description}</div> : null}
      </div>
    </label>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="rounded-[24px] border border-dashed border-[var(--line-strong)] bg-[var(--panel-2)] px-5 py-10 text-center">
      <div className="text-base font-semibold text-[var(--text)]">{title}</div>
      {description ? <div className="mx-auto mt-2 max-w-xl text-sm leading-6 text-[var(--muted)]">{description}</div> : null}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={cn("skeleton-block rounded-2xl", className)} aria-hidden="true" />;
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button onClick={toggleTheme} className="btn-secondary w-full px-4 py-3 text-sm" type="button">
      {theme === "light" ? "切换深色主题" : "切换浅色主题"}
    </button>
  );
}

