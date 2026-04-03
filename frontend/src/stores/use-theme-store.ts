// frontend/src/stores/use-theme-store.ts

import { create } from "zustand";

export type Theme = "geek" | "modern" | "eva-unit-01";

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
}

// 从 localStorage 读取初始值
function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "modern"; // SSR 环境下默认使用 modern
  const stored = localStorage.getItem("owl-theme");
  if (stored === "geek" || stored === "modern" || stored === "eva-unit-01") {
    return stored;
  }
  return "modern"; // 默认主题
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: getInitialTheme(),
  setTheme: (t) => {
    localStorage.setItem("owl-theme", t);
    set({ theme: t });
  },
}));