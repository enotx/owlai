// owlai/frontend/src/components/data/local-assets-tab.tsx

"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Database, Code2, FileText } from "lucide-react";
import DataSourcesTab from "./data-sources-tab";
import AssetPanel from "./asset-panel";

type SubTab = "data-sources" | "scripts" | "sops";

export default function LocalAssetsTab() {
  const [activeSubTab, setActiveSubTab] = useState<SubTab>("data-sources");

  const subTabs: { id: SubTab; label: string; icon: typeof Database }[] = [
    { id: "data-sources", label: "Data Sources", icon: Database },
    { id: "scripts", label: "Scripts", icon: Code2 },
    { id: "sops", label: "SOPs", icon: FileText },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Sub-tab bar */}
      <div className="flex border-b">
        {subTabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = tab.id === activeSubTab;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveSubTab(tab.id)}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors",
                isActive
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeSubTab === "data-sources" && <DataSourcesTab />}
        {activeSubTab === "scripts" && <AssetPanel filterType="scripts" />}
        {activeSubTab === "sops" && <AssetPanel filterType="sops" />}
      </div>
    </div>
  );
}