// frontend/src/components/settings/interface-view.tsx

"use client";

import { useThemeStore, type Theme } from "@/stores/use-theme-store";
import { useSettingsStore } from "@/stores/use-settings-store";
import { useTranslations } from "@/hooks/use-translations";
import { cn } from "@/lib/utils";
import { Monitor, Palette, Languages } from "lucide-react";

const themes: { id: Theme; name: string; description: string; preview: string }[] = [
  {
    id: "geek",
    name: "interface.themes.geek.name",
    description: "interface.themes.geek.description",
    preview: "bg-gradient-to-br from-gray-100 to-gray-300",
  },
  {
    id: "modern",
    name: "interface.themes.modern.name",
    description: "interface.themes.modern.description",
    preview: "bg-gradient-to-br from-slate-800 to-blue-900",
  },
  {
    id: "eva-unit-01",
    name: "interface.themes.evaUnit01.name",
    description: "interface.themes.evaUnit01.description",
    preview: "bg-gradient-to-br from-[#1a1029] via-[#2a1740] to-[#12081f]",
  },
];

const languages = [
  { code: "en", name: "interface.languages.en" },
  { code: "zh-cn", name: "interface.languages.zh-cn" },
  { code: "ja", name: "interface.languages.ja" },
];

export default function InterfaceView() {
  const { theme, setTheme } = useThemeStore();
  const { locale, setLocale } = useSettingsStore();
  const t = useTranslations();

  return (
    <div className="p-6 space-y-8 overflow-y-auto h-full">
      {/* Theme Section */}
      <section>
        <div className="flex items-center gap-2 mb-1">
          <Palette className="h-5 w-5 text-primary" />
          <h3 className="text-lg font-semibold">{t("interface.theme")}</h3>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          {t("interface.themeDescription")}
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 max-w-4xl">
          {themes.map((themeItem) => (
            <button
              key={themeItem.id}
              onClick={() => setTheme(themeItem.id)}
              className={cn(
                "group relative rounded-xl border-2 p-1 transition-all text-left",
                theme === themeItem.id
                  ? "border-primary ring-2 ring-primary/20"
                  : "border-border hover:border-muted-foreground/40"
              )}
            >
              {/* Preview swatch */}
              <div
                className={cn(
                  "h-24 rounded-lg mb-2",
                  themeItem.preview
                )}
              >
                {/* Mini layout preview */}
                <div className="flex h-full p-2 gap-1">
                  <div
                    className={cn(
                      "w-6 rounded",
                      themeItem.id === "modern"
                        ? "bg-slate-900/60"
                        : themeItem.id === "eva-unit-01"
                          ? "bg-[#241235]/90"
                          : "bg-gray-200/80"
                    )}
                  />
                  <div className="flex-1 flex flex-col gap-1">
                    <div
                      className={cn(
                        "h-2 rounded",
                        themeItem.id === "modern"
                          ? "bg-white/30"
                          : themeItem.id === "eva-unit-01"
                            ? "bg-[#b6ff00]/80"
                            : "bg-gray-300/60"
                      )}
                    />
                    <div
                      className={cn(
                        "flex-1 rounded",
                        themeItem.id === "eva-unit-01"
                          ? "bg-[#1a0a28]/80"
                          : "bg-white/20"
                      )}
                    />
                  </div>
                  <div
                    className={cn(
                      "w-8 rounded",
                      themeItem.id === "modern"
                        ? "bg-white/15"
                        : themeItem.id === "eva-unit-01"
                          ? "bg-[#2c163f]/90"
                          : "bg-gray-100/60"
                    )}
                  />
                </div>
              </div>
              {/* Label */}
              <div className="px-2 pb-2">
                <div className="font-medium text-sm">{t(themeItem.name)}</div>
                <div className="text-xs text-muted-foreground leading-snug mt-0.5">
                  {t(themeItem.description)}
                </div>
              </div>
              {/* Selected indicator */}
              {theme === themeItem.id && (
                <div className="absolute top-2 right-2 h-5 w-5 rounded-full bg-primary flex items-center justify-center">
                  <Monitor className="h-3 w-3 text-primary-foreground" />
                </div>
              )}
            </button>
          ))}
        </div>
      </section>

      {/* Language Section */}
      <section>
        <div className="flex items-center gap-2 mb-1">
          <Languages className="h-5 w-5 text-primary" />
          <h3 className="text-lg font-semibold">{t("interface.language")}</h3>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          {t("interface.languageDescription")}
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 max-w-4xl">
          {languages.map((lang) => (
            <button
              key={lang.code}
              onClick={() => setLocale(lang.code)}
              className={cn(
                "relative rounded-lg border-2 px-4 py-3 transition-all text-left",
                locale === lang.code
                  ? "border-primary ring-2 ring-primary/20 bg-primary/5"
                  : "border-border hover:border-muted-foreground/40"
              )}
            >
              <div className="font-medium text-sm">{t(lang.name)}</div>
              {locale === lang.code && (
                <div className="absolute top-2 right-2 h-4 w-4 rounded-full bg-primary flex items-center justify-center">
                  <div className="h-1.5 w-1.5 rounded-full bg-primary-foreground" />
                </div>
              )}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}