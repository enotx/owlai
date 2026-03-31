// frontend/src/app/theme-initializer.tsx

"use client";

import { useEffect } from "react";
import { useThemeStore } from "@/stores/use-theme-store";

/**
 * 将 theme store 的值同步到 <html data-theme="...">
 * 放在 body 内部即可，通过 DOM API 操作 <html>
 */
export function ThemeInitializer() {
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return null;
}