// frontend/src/app/page.tsx

"use client";

/**
 * 主页面：三栏布局
 * 左侧 Sidebar (240px) | 中间 Chat (flex) | 右侧 Data Panel (420px)
 */
import { useEffect, useState } from "react";
import TaskSidebar from "@/components/sidebar/task-sidebar";
import ChatArea from "@/components/chat/chat-area";
import DataPanel from "@/components/data/data-panel";
import { checkHealth } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { CircleCheck, CircleX, Loader2 } from "lucide-react";

export default function HomePage() {
  const [backendStatus, setBackendStatus] = useState<
    "checking" | "connected" | "disconnected"
  >("checking");

  /* 启动时检测后端连通性 */
  useEffect(() => {
    checkHealth()
      .then(() => setBackendStatus("connected"))
      .catch(() => setBackendStatus("disconnected"));
  }, []);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background">
      {/* 顶部状态条 */}
      <header className="flex h-10 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold tracking-tight">🦉 Owl</span>
          <span className="text-xs text-muted-foreground">AI Data Analyst</span>
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
        {/* 左侧：Task Sidebar */}
        <aside className="w-60 shrink-0">
          <TaskSidebar />
        </aside>

        {/* 中间：Chat Area */}
        <main className="flex-1 overflow-hidden">
          <ChatArea />
        </main>

        {/* 右侧：Data Panel */}
        <aside className="w-[420px] shrink-0">
          <DataPanel />
        </aside>
      </div>
    </div>
  );
}