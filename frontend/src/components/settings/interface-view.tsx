// frontend/src/components/settings/interface-view.tsx

"use client";

import { useThemeStore, type Theme } from "@/stores/use-theme-store";
import { cn } from "@/lib/utils";
import { Monitor, Palette } from "lucide-react";

const themes: { id: Theme; name: string; description: string; preview: string }[] = [
  {
    id: "geek",
    name: "Geek",
    description: "Clean monochrome interface with neutral tones. The original Owl experience.",
    preview: "bg-gradient-to-br from-gray-100 to-gray-300",
  },
  {
    id: "modern",
    name: "Modern",
    description: "Deep navy sidebar with blue accents. A polished, professional look.",
    preview: "bg-gradient-to-br from-slate-800 to-blue-900",
  },
  {
    id: "eva-unit-01",
    name: "Eva Unit-01",
    description: "Dark tactical purple with neon green highlights, inspired by EVA-01 command panels.",
    preview: "bg-gradient-to-br from-[#1a1029] via-[#2a1740] to-[#12081f]",
  },
];

export default function InterfaceView() {
  const { theme, setTheme } = useThemeStore();

  return (
    <div className="p-6 space-y-8 overflow-y-auto h-full">
      {/* Theme Section */}
      <section>
        <div className="flex items-center gap-2 mb-1">
          <Palette className="h-5 w-5 text-primary" />
          <h3 className="text-lg font-semibold">Theme</h3>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Choose a visual theme. Layout stays the same — only colors change.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 max-w-4xl">
          {themes.map((t) => (
            <button
              key={t.id}
              onClick={() => setTheme(t.id)}
              className={cn(
                "group relative rounded-xl border-2 p-1 transition-all text-left",
                theme === t.id
                  ? "border-primary ring-2 ring-primary/20"
                  : "border-border hover:border-muted-foreground/40"
              )}
            >
              {/* Preview swatch */}
              <div
                className={cn(
                  "h-24 rounded-lg mb-2",
                  t.preview
                )}
              >
                {/* Mini layout preview */}
                <div className="flex h-full p-2 gap-1">
                  <div
                    className={cn(
                      "w-6 rounded",
                      t.id === "modern"
                        ? "bg-slate-900/60"
                        : t.id === "eva-unit-01"
                          ? "bg-[#241235]/90"
                          : "bg-gray-200/80"
                    )}
                  />
                  <div className="flex-1 flex flex-col gap-1">
                    <div
                      className={cn(
                        "h-2 rounded",
                        t.id === "modern"
                          ? "bg-white/30"
                          : t.id === "eva-unit-01"
                            ? "bg-[#b6ff00]/80"
                            : "bg-gray-300/60"
                      )}
                    />
                    <div
                      className={cn(
                        "flex-1 rounded",
                        t.id === "eva-unit-01"
                          ? "bg-[#1a0a28]/80"
                          : "bg-white/20"
                      )}
                    />
                  </div>
                  <div
                    className={cn(
                      "w-8 rounded",
                      t.id === "modern"
                        ? "bg-white/15"
                        : t.id === "eva-unit-01"
                          ? "bg-[#2c163f]/90"
                          : "bg-gray-100/60"
                    )}
                  />
                </div>
              </div>
              {/* Label */}
              <div className="px-2 pb-2">
                <div className="font-medium text-sm">{t.name}</div>
                <div className="text-xs text-muted-foreground leading-snug mt-0.5">
                  {t.description}
                </div>
              </div>
              {/* Selected indicator */}
              {theme === t.id && (
                <div className="absolute top-2 right-2 h-5 w-5 rounded-full bg-primary flex items-center justify-center">
                  <Monitor className="h-3 w-3 text-primary-foreground" />
                </div>
              )}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}