"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { Card, SectionTitle, Skeleton } from "@/components/ui";

export default function FeishuBotsPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/extensions/feishu?tab=agents");
  }, [router]);

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="Redirecting" title="正在跳转到飞书集成中心" desc="Agent Bot 功能已并入飞书集成中心的“Agent Bots”标签页。" />
      </Card>
      <Skeleton className="h-[420px]" />
    </div>
  );
}
