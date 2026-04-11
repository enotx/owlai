// frontend/src/app/theme-initializer.tsx

"use client";

import { useEffect } from "react";
import { useThemeStore, type Theme } from "@/stores/use-theme-store";

/**
 * Themes that require the `dark` class on <html>.
 * When adding a new dark theme, just append its id here.
 */
const DARK_THEMES: Theme[] = ["eva-unit-01", "eva-unit-02"];

/**
 * Syncs the theme store value to:
 *   <html data-theme="...">   — drives CSS custom-property overrides
 *   <html class="dark">       — activates Tailwind `dark:` variants
 */
export function ThemeInitializer() {
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);

    if (DARK_THEMES.includes(theme)) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  return null;
}