// frontend/src/components/settings/settings-dialog.tsx

"use client";

/**
 * Settings 对话框：左侧导航 + 右侧内容区
 */
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useSettingsStore } from "@/stores/use-settings-store";
import { fetchProviders } from "@/lib/api";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import ProvidersView from "./providers-view";
import AgentsView from "./agents-view";
import SkillsView from "./skills-view";
import AboutView from "./about-view";



type MenuItem = {
  id: string;
  label: string;
  category?: string;
};

const menuItems: MenuItem[] = [
  { id: "interface", label: "Interface", category: "General" },
  { id: "providers", label: "Providers/Models", category: "LLM" },
  { id: "agents", label: "Agents", category: "LLM" },
  { id: "skills", label: "Skills", category: "Extensions" },
  { id: "misc", label: "Miscellaneous", category: "Other" },
  { id: "about", label: "About", category: "Other" },
];


export default function SettingsDialog() {
  const { isSettingsOpen, setSettingsOpen, setProviders, currentView, setCurrentView,
          selectedSettingsItem, setSelectedSettingsItem } =
      useSettingsStore();
  // const [selectedItem, setSelectedItem] = useState<string>("providers");

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
  };

  // 渲染右侧内容
  const renderContent = () => {
    if (selectedSettingsItem === "providers") {
      return <ProvidersView />;
    }
    if (selectedSettingsItem === "agents") {
      return <AgentsView />; 
    }

    if (selectedSettingsItem === "skills") {
      return <SkillsView />;
    }

    if (selectedSettingsItem === "about") {
      return <AboutView />;
    }
    
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Coming Soon
      </div>
    );
  };


  // 按 category 分组菜单项
  const groupedItems = menuItems.reduce((acc, item) => {
    const cat = item.category || "Other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {} as Record<string, MenuItem[]>);

  return (
    <Dialog open={isSettingsOpen} onOpenChange={setSettingsOpen}>
      <DialogContent
        className="w-[90vw] sm:w-[80vw] sm:max-w-[1600px] h-[85vh] p-0 gap-0"
        showCloseButton={false}
      >
        {/* 隐藏的标题，仅供屏幕阅读器使用 */}
        <DialogTitle className="sr-only">Settings</DialogTitle>
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-4 top-4 z-10 h-7 w-7 rounded-full"
            onClick={handleClose}
          >
            <X className="h-4 w-4" />
          </Button>
          <div className="flex h-full">
          {/* 左侧导航 */}
          <aside className="w-56 border-r bg-muted/30 flex flex-col">
            <div className="p-4">
              <h2 className="text-lg font-semibold">Settings</h2>
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

          {/* 右侧内容区 */}
          <main className="flex-1 overflow-hidden">{renderContent()}</main>
        </div>
      </DialogContent>
    </Dialog>
  );
}