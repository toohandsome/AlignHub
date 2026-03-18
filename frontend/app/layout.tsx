import "./globals.css";

import { ThemeProvider } from "@/components/theme-provider";
import { Nav, Shell } from "@/components/ui";

export const metadata = {
  title: "AlignHub",
  description: "多智能体协同、共识收敛与联合决策平台"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <ThemeProvider>
          <Shell>
            <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)] lg:gap-6">
              <Nav />
              <main className="min-w-0">{children}</main>
            </div>
          </Shell>
        </ThemeProvider>
      </body>
    </html>
  );
}
