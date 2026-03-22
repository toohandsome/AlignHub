import Link from "next/link";

import { API_BASE } from "@/lib/api";
import { Badge, Card, SectionTitle } from "@/components/ui";

const capabilities = [
  "Provider / Model 配置与连通性测试",
  "Agent 角色、工具、Skill、MCP 统一编排",
  "讨论会话创建、启动与轮次控制",
  "实时事件流、Tool Log 与最终报告回放",
  "飞书群聊 / Agent Bot 协同接入",
  "工作区复制、上下文压缩与运行治理"
];

const quickLinks = [
  { href: "/providers", title: "配置模型底座", description: "统一管理 Provider、Model 与连接测试。" },
  { href: "/agents", title: "编排 Agent 角色", description: "组合模型、工具、Skill、MCP 与主持人角色。" },
  { href: "/sessions", title: "启动讨论流程", description: "创建会话、安排发言顺序并直接启动 Run。" },
  { href: "/history", title: "追踪历史运行", description: "查看报告、事件流与完整执行回放。" }
];

export default function HomePage() {
  return (
    <div className="grid gap-6">
      <section className="surface relative overflow-hidden rounded-[32px] border px-6 py-7 md:px-8 md:py-10">
        <div className="absolute inset-y-0 right-0 hidden w-[36%] bg-[radial-gradient(circle_at_top,rgba(79,124,255,0.24),transparent_58%),radial-gradient(circle_at_bottom,rgba(124,58,237,0.16),transparent_48%)] lg:block" />
        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.72fr)] lg:items-end">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--line-strong)] bg-[var(--brand-soft)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-[var(--brand-strong)]">
              AlignHub Control Center
            </div>
            <h1 className="mt-5 max-w-3xl text-4xl font-semibold tracking-tight text-[var(--text)] md:text-5xl">让多智能体协同、收敛与决策真正进入可运营状态。</h1>
            <p className="mt-4 max-w-2xl text-base leading-8 text-[var(--muted)] md:text-lg">
              AlignHub 将模型底座、角色编排、讨论流程、实时回放与飞书接入整合到同一工作台，帮助你更快搭建可观察、可复用、可落地的多智能体系统。
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/sessions" className="btn-primary inline-flex items-center rounded-2xl px-5 py-3 text-sm font-medium text-white">
                立即创建讨论会话
              </Link>
              <Link href="/agents" className="btn-secondary inline-flex items-center rounded-2xl px-5 py-3 text-sm font-medium">
                先配置 Agent
              </Link>
            </div>
            <div className="mt-6 flex flex-wrap gap-2">
              <Badge>API：{API_BASE}</Badge>
              <Badge tone="success">Next.js 16</Badge>
              <Badge tone="success">React 19</Badge>
              <Badge>Tailwind CSS 4</Badge>
            </div>
          </div>

          <div className="grid gap-3">
            <div className="rounded-[28px] border border-[var(--line-strong)] bg-[var(--panel-2)] p-5">
              <div className="text-sm text-[var(--muted)]">推荐使用路径</div>
              <div className="mt-3 grid gap-3">
                {[
                  "1. 先完成 Provider / Model 连接验证",
                  "2. 组合 Agent 的角色、工具、Skill、MCP",
                  "3. 创建会话并明确 Moderator",
                  "4. 启动 Run，实时观察事件流与报告"
                ].map((item) => (
                  <div key={item} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-3)] px-4 py-3 text-sm text-[var(--text)]">
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <Card>
          <SectionTitle eyebrow="Capabilities" title="核心能力覆盖完整协同链路" desc="从模型底座到运行回放，关键节点都可以在一个界面中完成配置与观察。" />
          <div className="grid gap-3 md:grid-cols-2">
            {capabilities.map((item) => (
              <div key={item} className="rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-4 text-sm leading-7 text-[var(--text)]">
                {item}
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle eyebrow="Quick Start" title="高频入口" desc="把最常用的配置流压缩到最短路径，减少切换成本。" />
          <div className="grid gap-3">
            {quickLinks.map((item) => (
              <Link key={item.href} href={item.href} className="group rounded-[24px] border border-[var(--line)] bg-[var(--panel-2)] px-4 py-4 transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]">
                <div className="text-base font-medium text-[var(--text)]">{item.title}</div>
                <div className="mt-1 text-sm leading-6 text-[var(--muted)]">{item.description}</div>
              </Link>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
