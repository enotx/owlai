// frontend/src/stores/use-theme-store.ts

import { create } from "zustand";

export type Theme = "geek" | "modern";

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
}

// 从 localStorage 读取初始值
function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "geek";
  const stored = localStorage.getItem("owl-theme");
  if (stored === "geek" || stored === "modern") return stored;
  return "geek";
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: getInitialTheme(),
  setTheme: (t) => {
    localStorage.setItem("owl-theme", t);
    set({ theme: t });
  },
}));