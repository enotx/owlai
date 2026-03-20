// frontend/src/app/page.tsx

"use client";

/**
 * 主页面：三栏布局
 * 左侧固定 200px | 中间最小 400px | 右侧动态
 * 中+右 > 800px 时按 55:45 分配，否则右侧获得剩余空间
 */
import { useEffect, useState, useCallback } from "react";
import TaskSidebar from "@/components/sidebar/task-sidebar";
import ChatArea from "@/components/chat/chat-area";
import DataPanel from "@/components/data/data-panel";
import { Badge } from "@/components/ui/badge";
import SettingsDialog from "@/components/settings/settings-dialog";
import DatabaseWarningDialog from "@/components/database/database-warning-dialog";
import OnboardingDialog from "@/components/onboarding/onboarding-dialog";
import { CircleCheck, CircleX, Loader2 } from "lucide-react";
import { useBackend } from "@/contexts/backend-context";
import { useDatabase } from "@/contexts/database-context";
import { useOnboarding } from "@/contexts/onboarding-context";
import { fetchProviders, fetchAgentConfigs } from "@/lib/api";
import { useSettingsStore } from "@/stores/use-settings-store";


/** 布局常量 */
const LEFT_WIDTH = 200;       // 左侧固定宽度 px
const MID_MIN = 400;          // 中间最小宽度 px
const RIGHT_MIN = 300;        // 右侧最小宽度 px
const SPLIT_THRESHOLD = 800;  // 中+右超过此值时启用比例分配

/** 根据可分配宽度计算中间和右侧的宽度 */
function calcPanelWidths(totalWidth: number): { mid: number; right: number } {
  const available = totalWidth - LEFT_WIDTH; // 中+右可用空间

  if (available >= SPLIT_THRESHOLD) {
    // 空间充足：55:45 比例分配
    return {
      mid: Math.round(available * 0.55),
      right: Math.round(available * 0.45),
    };
  } else {
    // 空间不足：中间优先保底 MID_MIN，右侧获得剩余
    const mid = Math.max(MID_MIN, available - RIGHT_MIN);
    const right = available - mid;
    return { mid, right };
  }
}

export default function HomePage() {
  // 使用 useBackend hook 替代本地状态
  const { status: backendStatus } = useBackend();
  const { shouldShowWarning: showDatabaseWarning, dismissWarning: dismissDatabaseWarning } = useDatabase();
  const { shouldShowOnboarding, skipOnboarding, recheckConfiguration } = useOnboarding();


  const [panelWidths, setPanelWidths] = useState<{ mid: number; right: number }>(
    () => calcPanelWidths(1280)
  );

  const handleResize = useCallback(() => {
    setPanelWidths(calcPanelWidths(window.innerWidth));
  }, []);

  useEffect(() => {
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [handleResize]);

  // 后端就绪后，拉取 Providers 和 AgentConfigs 到全局 store
  useEffect(() => {
    if (backendStatus !== "connected") return;
    const { setProviders, setAgentConfigs } = useSettingsStore.getState();
    fetchProviders()
      .then((res) => setProviders(res.data ?? []))
      .catch((err) => console.error("Failed to fetch providers:", err));
    fetchAgentConfigs()
      .then((res) => setAgentConfigs(res.data ?? []))
      .catch((err) => console.error("Failed to fetch agent configs:", err));
  }, [backendStatus]);


  const handleOnboardingClose = () => {
    // 重新检测配置（如果用户通过激活码或手动配置完成）
    recheckConfiguration();
    // 标记为已跳过（临时状态，刷新页面后失效）
    skipOnboarding();
  };
  const handleDatabaseWarningClose = () => {
    dismissDatabaseWarning();
  };
  // 优先级控制：只有在数据库兼容且后端连接正常时才显示 Onboarding
  const shouldShowOnboardingDialog = 
    !showDatabaseWarning && 
    backendStatus === "connected" && 
    shouldShowOnboarding;

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background">
      {/* 顶部状态条 */}
      <header className="flex h-10 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold tracking-tight">🦉 Owl.AI</span>
          <span className="text-xs text-muted-foreground">An AI Data Analyst</span>
        </div>
        <Badge
          variant={backendStatus === "connected" ? "default" : "destructive"}
          className="gap-1 text-[10px]"
        >
          {backendStatus === "checking" && (
            <Loader2 className="h-3 w-3 animate-spin" />
          )}
          {backendStatus === "connected" && (
            <CircleCheck className="h-3 w-3" />
          )}
          {backendStatus === "disconnected" && (
            <CircleX className="h-3 w-3" />
          )}
          {backendStatus === "checking"
            ? "Connecting..."
            : backendStatus === "connected"
              ? "Backend Connected"
              : "Backend Offline"}
        </Badge>
      </header>

      {/* 三栏主体 */}
      <div className="flex flex-1 overflow-hidden">

        {/* 左侧：Task Sidebar，固定 200px */}
        <aside
          className="shrink-0 overflow-hidden"
          style={{ width: LEFT_WIDTH }}
        >
          <TaskSidebar />
        </aside>

        {/* 中间：Chat Area，动态宽度，保底 MID_MIN */}
        <main
          className="overflow-hidden"
          style={{ width: panelWidths.mid, minWidth: MID_MIN }}
        >
          <ChatArea />
        </main>

        {/* 右侧：Data Panel，动态宽度，保底 RIGHT_MIN */}
        <aside
          className="shrink-0 overflow-hidden"
          style={{ width: panelWidths.right, minWidth: RIGHT_MIN }}
        >
          <DataPanel />
        </aside>

      </div>
      {/* 设置对话框 */}
      <SettingsDialog />
      <DatabaseWarningDialog 
        open={showDatabaseWarning} 
        onClose={handleDatabaseWarningClose} 
      />

      {/* <OnboardingDialog 
        open={shouldShowOnboardingDialog} 
        onClose={handleOnboardingClose} 
      /> */}
    </div>
  );
}