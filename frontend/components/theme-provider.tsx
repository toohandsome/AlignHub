"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

type Theme = "light" | "dark";

const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void }>({
  theme: "light",
  toggleTheme: () => undefined
});

/**
 * 全局主题提供器。
 * 负责：
 * - 从 localStorage 恢复用户上次选择
 * - 同步到 html data-theme 属性
 * - 暴露主题切换能力给任意子组件
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const stored = window.localStorage.getItem("app-theme") as Theme | null;
    const nextTheme = stored ?? "light";
    setTheme(nextTheme);
    document.documentElement.setAttribute("data-theme", nextTheme);
  }, []);

  const value = useMemo(
    () => ({
      theme,
      toggleTheme: () => {
        const next = theme === "light" ? "dark" : "light";
        setTheme(next);
        document.documentElement.setAttribute("data-theme", next);
        window.localStorage.setItem("app-theme", next);
      }
    }),
    [theme]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/**
 * 主题上下文快捷访问 Hook。
 */
export function useTheme() {
  return useContext(ThemeContext);
}
