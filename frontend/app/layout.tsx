import "./globals.css";

import { ThemeProvider } from "@/components/theme-provider";
import { Nav, Shell, ToastProvider } from "@/components/ui";

export const metadata = {
  title: "AlignHub",
  description: "多智能体协同、共识收敛与联合决策平台"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <ToastProvider>
            <Shell>
              <div className="grid gap-4 lg:block">
                <Nav />
                <main className="min-w-0 pt-[78px] lg:pl-[292px] lg:pt-0">
                  <div className="mx-auto min-h-screen max-w-[1500px] lg:px-8 lg:py-8">{children}</div>
                </main>
              </div>
            </Shell>
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
