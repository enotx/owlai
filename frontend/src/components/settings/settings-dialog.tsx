// frontend/src/components/settings/settings-dialog.tsx

"use client";

/**
 * Settings 对话框：
 * - Desktop: 左侧导航 + 右侧内容区（并排）
 * - Mobile:  全屏，导航列表 ↔ 内容页 两级切换
 */
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useSettingsStore } from "@/stores/use-settings-store";
import { useTranslations } from "@/hooks/use-translations";
import { fetchProviders } from "@/lib/api";
import { cn } from "@/lib/utils";
import { X, ArrowLeft, Settings, Cpu, Bot, Puzzle, Info, Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import ProvidersView from "./providers-view";
import AgentsView from "./agents-view";
import SkillsView from "./skills-view";
import AboutView from "./about-view";
import InterfaceView from "./interface-view";

type MenuItem = {
  id: string;
  label: string;
  category?: string;
  icon: React.ComponentType<{ className?: string }>;
};

export default function SettingsDialog() {
  const {
    isSettingsOpen,
    setSettingsOpen,
    setProviders,
    currentView,
    setCurrentView,
    selectedSettingsItem,
    setSelectedSettingsItem,
  } = useSettingsStore();
  const t = useTranslations("settings");

  // Mobile: whether we're showing the content view (true) or the nav list (false)
  const [mobileShowContent, setMobileShowContent] = useState(false);

  const menuItems: MenuItem[] = [
    { id: "interface", label: t("interface"), category: t("categories.general"), icon: Palette },
    { id: "providers", label: t("providers"), category: t("categories.llm"), icon: Cpu },
    { id: "agents", label: t("agents"), category: t("categories.llm"), icon: Bot },
    { id: "skills", label: t("skills"), category: t("categories.extensions"), icon: Puzzle },
    { id: "misc", label: t("miscellaneous"), category: t("categories.other"), icon: Settings },
    { id: "about", label: t("about"), category: t("categories.other"), icon: Info },
  ];

  // 加载 Providers 数据
  useEffect(() => {
    if (isSettingsOpen) {
      fetchProviders()
        .then((res) => setProviders(res.data))
        .catch(() => setProviders([]));
    }
  }, [isSettingsOpen, setProviders]);

  // 关闭时重置状态
  const handleClose = () => {
    setSettingsOpen(false);
    setCurrentView("list");
    setSelectedSettingsItem("providers");
    setMobileShowContent(false);
  };

  // Mobile: 选择菜单项后切换到内容视图
  const handleSelectItem = (id: string) => {
    setSelectedSettingsItem(id);
    setMobileShowContent(true);
  };

  // Mobile: 从内容视图返回导航列表
  const handleMobileBack = () => {
    setMobileShowContent(false);
  };

  // 渲染右侧内容
  const renderContent = () => {
    switch (selectedSettingsItem) {
      case "interface":
        return <InterfaceView />;
      case "providers":
        return <ProvidersView />;
      case "agents":
        return <AgentsView />;
      case "skills":
        return <SkillsView />;
      case "about":
        return <AboutView />;
      default:
        return (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            {t("comingSoon")}
          </div>
        );
    }
  };

  // 按 category 分组菜单项
  const groupedItems = menuItems.reduce(
    (acc, item) => {
      const cat = item.category || "Other";
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(item);
      return acc;
    },
    {} as Record<string, MenuItem[]>
  );

  // 当前选中项的 label（用于移动端标题）
  const currentItemLabel =
    menuItems.find((m) => m.id === selectedSettingsItem)?.label || t("title");

  return (
    <Dialog open={isSettingsOpen} onOpenChange={setSettingsOpen}>
      <DialogContent
        className={cn(
          "p-0 gap-0",
          // Desktop
          "sm:w-[80vw] sm:max-w-[1600px] sm:h-[85vh]",
          // Mobile: full screen
          "w-screen h-screen sm:w-[80vw] sm:h-[85vh] max-w-none sm:max-w-[1600px] rounded-none sm:rounded-lg"
        )}
        showCloseButton={false}
      >
        {/* 隐藏的标题，仅供屏幕阅读器使用 */}
        <DialogTitle className="sr-only">{t("title")}</DialogTitle>

        {/* ═══ Desktop Layout: side-by-side ═══ */}
        <div className="hidden sm:flex h-full min-h-0">
          {/* Close button */}
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-4 top-4 z-10 h-7 w-7 rounded-full"
            onClick={handleClose}
          >
            <X className="h-4 w-4" />
          </Button>

          {/* Left nav */}
          <aside className="w-56 border-r bg-muted/30 flex flex-col">
            <div className="p-4">
              <h2 className="text-lg font-semibold">{t("title")}</h2>
            </div>
            <Separator />
            <div className="flex-1 overflow-y-auto p-2">
              {Object.entries(groupedItems).map(([category, items]) => (
                <div key={category} className="mb-4">
                  <div className="px-3 py-2 text-xs font-bold text-muted-foreground">
                    {category}
                  </div>
                  {items.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => setSelectedSettingsItem(item.id)}
                      className={cn(
                        "w-full text-left px-3 py-2 text-sm rounded-md transition-colors",
                        selectedSettingsItem === item.id
                          ? "bg-primary text-primary-foreground"
                          : "hover:bg-accent hover:text-accent-foreground"
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </aside>

          {/* Right content */}
          <main className="flex-1 min-h-0 overflow-hidden">{renderContent()}</main>
        </div>

        {/* ═══ Mobile Layout: nav list ↔ content page ═══ */}
        <div className="flex sm:hidden flex-col h-full">
          {!mobileShowContent ? (
            /* ── Navigation List ── */
            <div className="flex flex-col h-full">
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b">
                <h2 className="text-lg font-semibold">{t("title")}</h2>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-full"
                  onClick={handleClose}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              {/* Menu items */}
              <div className="flex-1 overflow-y-auto">
                {Object.entries(groupedItems).map(([category, items]) => (
                  <div key={category}>
                    <div className="px-4 pt-4 pb-1 text-xs font-bold text-muted-foreground uppercase tracking-wider">
                      {category}
                    </div>
                    {items.map((item) => {
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.id}
                          onClick={() => handleSelectItem(item.id)}
                          className={cn(
                            "w-full flex items-center gap-3 px-4 py-3 text-sm transition-colors",
                            "active:bg-accent/70",
                            selectedSettingsItem === item.id
                              ? "bg-accent text-accent-foreground"
                              : "hover:bg-accent/50"
                          )}
                        >
                          <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
                          <span className="flex-1 text-left">{item.label}</span>
                          <ArrowLeft className="h-4 w-4 text-muted-foreground rotate-180" />
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            /* ── Content Page ── */
            <div className="flex flex-col h-full">
              {/* Header with back */}
              <div className="flex items-center gap-2 px-2 py-2 border-b shrink-0">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  onClick={handleMobileBack}
                >
                  <ArrowLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm font-semibold truncate">
                  {currentItemLabel}
                </span>
                <div className="flex-1" />
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-full shrink-0"
                  onClick={handleClose}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              {/* Content */}
              <main className="flex-1 min-h-0 overflow-hidden">
                {renderContent()}
              </main>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}