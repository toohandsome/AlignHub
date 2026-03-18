import Link from "next/link";

import { Badge, Card, SectionTitle } from "@/components/ui";
import { API_BASE } from "@/lib/api";

export default function HomePage() {
  const features = [
    "智能体配置与角色管理",
    "Provider / Model 配置与连通性测试",
    "讨论会话创建与启动",
    "WebSocket 实时事件流",
    "工具调用可视化",
    "Markdown 最终报告渲染",
    "讨论过程回放",
    "飞书群聊协同接入"
  ];

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle title="AlignHub" desc="面向多智能体协同、共识收敛与联合决策的控制台。" />
        <div className="flex flex-wrap gap-3">
          <Badge>API：{API_BASE}</Badge>
          <Badge tone="success">React + Next.js</Badge>
          <Badge tone="success">TailwindCSS</Badge>
          <Badge tone="success">AlignHub</Badge>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        <Card>
          <SectionTitle title="能力清单" desc="聚焦多智能体协同、对齐与决策的完整链路。" />
          <ul className="space-y-2 text-sm">
            {features.map((feature) => (
              <li key={feature} className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-3 text-[var(--text)]">
                {feature}
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <SectionTitle title="快速入口" desc="从这里进入核心管理页面。" />
          <div className="grid gap-3">
            <Link href="/providers" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              进入 Provider / Model 管理
            </Link>
            <Link href="/skills" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              进入 Skill 管理
            </Link>
            <Link href="/mcps" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              进入 MCP 管理
            </Link>
            <Link href="/agents" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              进入 Agent 管理
            </Link>
            <Link href="/sessions" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              创建 / 启动讨论会话
            </Link>
            <Link href="/history" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              查看历史会话与回放
            </Link>
            <Link href="/extensions/feishu" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              配置飞书集成
            </Link>
            <Link href="/extensions/feishu/bots" className="rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-sm text-[var(--text)] transition hover:border-sky-400">
              管理飞书机器人
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
