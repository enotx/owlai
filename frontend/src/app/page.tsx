// frontend/src/app/page.tsx

"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import TaskSidebar from "@/components/sidebar/task-sidebar";
import ChatArea from "@/components/chat/chat-area";
import DataPanel from "@/components/data/data-panel";
import { Badge } from "@/components/ui/badge";
import SettingsDialog from "@/components/settings/settings-dialog";
import DatabaseWarningDialog from "@/components/database/database-warning-dialog";
import {
  CircleCheck,
  CircleX,
  Loader2,
  Search,
  Bell,
  User,
  ChevronLeft,
  ChevronRight,
  Plus,
  Settings,
  BarChart3,
  HelpCircle,
  TableProperties,
} from "lucide-react";
import { useBackend } from "@/contexts/backend-context";
import { useDatabase } from "@/contexts/database-context";
import { useOnboarding } from "@/contexts/onboarding-context";
import {
  fetchProviders,
  fetchAgentConfigs,
  checkForUpdate,
  getPlatformInfo,
} from "@/lib/api";
import { useSettingsStore } from "@/stores/use-settings-store";
import { useTaskStore } from "@/stores/use-task-store";
import { cn } from "@/lib/utils";

/* ══════════════════════════════════════════
   Layout constants
   ══════════════════════════════════════════ */
const LEFT_DEFAULT = 240;
const LEFT_MIN = 200;
const LEFT_MAX = 360;
const LEFT_COLLAPSED = 56;

const RIGHT_DEFAULT = 420;
const RIGHT_MIN = 280;
const RIGHT_MAX = 640;
const RIGHT_COLLAPSED = 0; // fully hidden, only chevron visible

const MID_MIN = 380;

/* ══════════════════════════════════════════
   localStorage helpers
   ══════════════════════════════════════════ */
function loadPanelState() {
  if (typeof window === "undefined") {
    return { leftWidth: LEFT_DEFAULT, rightWidth: RIGHT_DEFAULT, leftCollapsed: false, rightCollapsed: false };
  }
  try {
    const raw = localStorage.getItem("owl-panel-state");
    if (raw) {
      const p = JSON.parse(raw);
      return {
        leftWidth: Math.min(LEFT_MAX, Math.max(LEFT_MIN, p.leftWidth ?? LEFT_DEFAULT)),
        rightWidth: Math.min(RIGHT_MAX, Math.max(RIGHT_MIN, p.rightWidth ?? RIGHT_DEFAULT)),
        leftCollapsed: p.leftCollapsed ?? false,
        rightCollapsed: p.rightCollapsed ?? false,
      };
    }
  } catch { /* ignore */ }
  return { leftWidth: LEFT_DEFAULT, rightWidth: RIGHT_DEFAULT, leftCollapsed: false, rightCollapsed: false };
}

function savePanelState(state: { leftWidth: number; rightWidth: number; leftCollapsed: boolean; rightCollapsed: boolean }) {
  try { localStorage.setItem("owl-panel-state", JSON.stringify(state)); } catch { /* ignore */ }
}

/* ══════════════════════════════════════════
   Resize handle (drag strip)
   ══════════════════════════════════════════ */
function ResizeHandle({ onDragStart }: { onDragStart: (e: React.MouseEvent) => void }) {
  return (
    <div
      className="group relative z-10 flex w-1.5 shrink-0 cursor-col-resize items-center justify-center transition-colors hover:bg-primary/10 active:bg-primary/20"
      onMouseDown={onDragStart}
    >
      <div className="h-8 w-0.5 rounded-full bg-border transition-colors group-hover:bg-primary/40 group-active:bg-primary/60" />
    </div>
  );
}

/* ══════════════════════════════════════════
   Edge chevron toggle (sits on panel border)
   ══════════════════════════════════════════ */
function EdgeChevron({
  side,
  collapsed,
  onClick,
}: {
  side: "left" | "right";
  collapsed: boolean;
  onClick: () => void;
}) {
  // Left panel: collapsed → show ">" to expand, expanded → show "<" to collapse
  // Right panel: collapsed → show "<" to expand, expanded → show ">" to collapse
  const showRight = (side === "left" && collapsed) || (side === "right" && !collapsed);

  return (
    <button
      onClick={onClick}
      className={cn(
        "absolute top-1/2 -translate-y-1/2 z-20",
        "flex h-8 w-4 items-center justify-center",
        "bg-card border shadow-sm transition-colors hover:bg-accent",
        // Positioning: on the edge between panels
        side === "left" ? "-right-4 rounded-r-md border-l-0" : "-left-4 rounded-l-md border-r-0"
      )}
      title={collapsed ? "Expand" : "Collapse"}
    >
      {showRight ? (
        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
      ) : (
        <ChevronLeft className="h-3.5 w-3.5 text-muted-foreground" />
      )}
    </button>
  );
}

/* ══════════════════════════════════════════
   Left collapsed mini sidebar
   ══════════════════════════════════════════ */
function CollapsedSidebar({
  onNewTask,
  onOpenSettings,
}: {
  onNewTask: () => void;
  onOpenSettings: () => void;
}) {
  return (
    <div
      className="flex h-full w-full flex-col items-center py-4 gap-3"
      style={{
        background: "var(--owl-sidebar-bg)",
        borderRight: "1px solid var(--owl-sidebar-border)",
      }}
    >
      {/* Logo */}
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
        style={{ background: "var(--owl-btn-primary-bg)" }}
      >
        <span className="text-sm" style={{ color: "var(--owl-btn-primary-fg)" }}>🦉</span>
      </div>

      {/* New task */}
      <button
        onClick={onNewTask}
        className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:opacity-90"
        style={{ background: "var(--owl-btn-primary-bg)", color: "var(--owl-btn-primary-fg)" }}
        title="New Action"
      >
        <Plus className="h-4 w-4" />
      </button>

      {/* Task list icon */}
      <button
        className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors"
        style={{ color: "var(--owl-sidebar-muted)" }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
        title="Tasks"
      >
        <BarChart3 className="h-4 w-4" />
      </button>

      <div className="flex-1" />

      {/* Settings */}
      <button
        onClick={onOpenSettings}
        className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors"
        style={{ color: "var(--owl-sidebar-muted)" }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
        title="Settings"
      >
        <Settings className="h-4 w-4" />
      </button>

      {/* Help */}
      <button
        className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors"
        style={{ color: "var(--owl-sidebar-muted)" }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
        title="Help"
      >
        <HelpCircle className="h-4 w-4" />
      </button>
    </div>
  );
}

/* ══════════════════════════════════════════
   Main page
   ══════════════════════════════════════════ */
export default function HomePage() {
  const { status: backendStatus } = useBackend();
  const { shouldShowWarning: showDatabaseWarning, dismissWarning: dismissDatabaseWarning } = useDatabase();
  const { shouldShowOnboarding, skipOnboarding, recheckConfiguration } = useOnboarding();
  const { updateStatus, setUpdateStatus, setUpdateInfo, setSettingsOpen, setSelectedSettingsItem } = useSettingsStore();
  const isTauriEnv = typeof window !== "undefined" && "__TAURI__" in window;

  /* ── Panel state ── */
  const [leftWidth, setLeftWidth] = useState(LEFT_DEFAULT);
  const [rightWidth, setRightWidth] = useState(RIGHT_DEFAULT);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [isDragging, setIsDragging] = useState<"left" | "right" | null>(null);

  const stateRef = useRef({ leftWidth, rightWidth, leftCollapsed, rightCollapsed });
  useEffect(() => {
    stateRef.current = { leftWidth, rightWidth, leftCollapsed, rightCollapsed };
  }, [leftWidth, rightWidth, leftCollapsed, rightCollapsed]);

  // Load from localStorage
  useEffect(() => {
    const saved = loadPanelState();
    setLeftWidth(saved.leftWidth);
    setRightWidth(saved.rightWidth);
    setLeftCollapsed(saved.leftCollapsed);
    setRightCollapsed(saved.rightCollapsed);
  }, []);

  // Persist
  useEffect(() => {
    savePanelState({ leftWidth, rightWidth, leftCollapsed, rightCollapsed });
  }, [leftWidth, rightWidth, leftCollapsed, rightCollapsed]);

  /* ── Drag logic ── */
  const handleDragStart = useCallback(
    (side: "left" | "right") => (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(side);
      const startX = e.clientX;
      const startLeftW = stateRef.current.leftWidth;
      const startRightW = stateRef.current.rightWidth;

      const onMouseMove = (ev: MouseEvent) => {
        const delta = ev.clientX - startX;
        const totalWidth = window.innerWidth;

        if (side === "left") {
          const newLeft = Math.min(LEFT_MAX, Math.max(LEFT_MIN, startLeftW + delta));
          const effectiveRight = stateRef.current.rightCollapsed ? 0 : stateRef.current.rightWidth;
          if (totalWidth - newLeft - effectiveRight - 3 >= MID_MIN) {
            setLeftWidth(newLeft);
          }
        } else {
          const newRight = Math.min(RIGHT_MAX, Math.max(RIGHT_MIN, startRightW - delta));
          const effectiveLeft = stateRef.current.leftCollapsed ? LEFT_COLLAPSED : stateRef.current.leftWidth;
          if (totalWidth - effectiveLeft - newRight - 3 >= MID_MIN) {
            setRightWidth(newRight);
          }
        }
      };

      const onMouseUp = () => {
        setIsDragging(null);
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    []
  );

  /* ── Collapse/Expand ── */
  const toggleLeftCollapsed = useCallback(() => setLeftCollapsed((p) => !p), []);
  const toggleRightCollapsed = useCallback(() => setRightCollapsed((p) => !p), []);

  /* ── New task from collapsed sidebar ── */
  const handleCollapsedNewTask = useCallback(async () => {
    const { createTask } = await import("@/lib/api");
    const taskStore = useTaskStore.getState();
    const title = `Task ${taskStore.tasks.length + 1}`;
    const res = await createTask(title);
    taskStore.addTask(res.data);
    taskStore.setCurrentTaskId(res.data.id);
    setLeftCollapsed(false);
  }, []);

  /* ── Effective widths ── */
  const effectiveLeft = leftCollapsed ? LEFT_COLLAPSED : leftWidth;
  const effectiveRight = rightCollapsed ? 0 : rightWidth;

  /* ── Auto update check (Tauri) ── */
  useEffect(() => {
    if (!isTauriEnv || backendStatus !== "connected") return;
    if (useSettingsStore.getState().updateStatus !== "idle") return;
    const timer = setTimeout(async () => {
      const store = useSettingsStore.getState();
      store.setUpdateStatus("checking");
      try {
        const { getVersion } = await import("@tauri-apps/api/app");
        const currentVersion = await getVersion();
        let plat = "macos", arch = "aarch64";
        try {
          const os = await import("@tauri-apps/plugin-os");
          plat = (await os.platform()) === "windows" ? "windows" : "macos";
          arch = (await os.arch()) === "aarch64" ? "aarch64" : "x86_64";
        } catch {
          const info = await getPlatformInfo();
          plat = info.platform; arch = info.arch;
        }
        const result = await checkForUpdate(currentVersion, plat, arch);
        store.setUpdateInfo(result);
        store.setUpdateStatus(result.has_update ? "has_update" : "up_to_date");
      } catch {
        store.setUpdateStatus("idle");
      }
    }, 5000);
    return () => clearTimeout(timer);
  }, [isTauriEnv, backendStatus]);

  const handleUpdateBadgeClick = useCallback(() => {
    setSelectedSettingsItem("about");
    setSettingsOpen(true);
  }, [setSelectedSettingsItem, setSettingsOpen]);

  /* ── Providers / AgentConfigs ── */
  useEffect(() => {
    if (backendStatus !== "connected") return;
    const s = useSettingsStore.getState();
    fetchProviders().then((r) => s.setProviders(r.data ?? [])).catch(() => {});
    fetchAgentConfigs().then((r) => s.setAgentConfigs(r.data ?? [])).catch(() => {});
  }, [backendStatus]);

  return (
    <div
      className={cn("flex h-screen w-screen overflow-hidden", isDragging && "select-none")}
      style={{ background: "var(--owl-workspace-bg)" }}
    >
      {/* Drag overlay */}
      {isDragging && <div className="fixed inset-0 z-50 cursor-col-resize" />}

      {/* ═══ Left Sidebar ═══ */}
      <aside
        className="relative shrink-0 transition-[width] duration-200 ease-out"
        style={{ width: effectiveLeft }}
      >
        {/* overflow-hidden 放在内容容器上，不裁剪 chevron */}
        <div className="h-full w-full overflow-hidden">
          {leftCollapsed ? (
            <CollapsedSidebar
              onNewTask={handleCollapsedNewTask}
              onOpenSettings={() => setSettingsOpen(true)}
            />
          ) : (
            <TaskSidebar />
          )}
        </div>
        <EdgeChevron side="left" collapsed={leftCollapsed} onClick={toggleLeftCollapsed} />
      </aside>


      {/* ═══ Left Resize Handle (only when expanded) ═══ */}
      {!leftCollapsed && <ResizeHandle onDragStart={handleDragStart("left")} />}

      {/* ═══ Center + Right ═══ */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">

        {/* ─── Top Bar ─── */}
        <header
          className="flex h-14 shrink-0 items-center justify-between px-6"
          style={{
            background: "var(--owl-topbar-bg)",
            borderBottom: "1px solid var(--owl-topbar-border)",
          }}
        >
          <div
            className="flex items-center gap-2 rounded-xl border px-3 py-1.5 w-[360px] transition-colors"
            style={{
              borderColor: "var(--owl-topbar-pill-border)",
              background: "var(--owl-topbar-search-bg)",
              color: "var(--owl-topbar-search-fg)",
            }}
          >
            <Search
              className="h-4 w-4"
              style={{ color: "var(--owl-topbar-search-placeholder)" }}
            />
            <span
              className="text-sm"
              style={{ color: "var(--owl-topbar-search-placeholder)" }}
            >
              Search workspace, assets, or logs...
            </span>
          </div>
          <div className="flex items-center gap-3">
            {isTauriEnv && updateStatus !== "idle" && (
              <Badge
                variant="outline"
                className="gap-1 text-[10px] cursor-pointer hover:opacity-80 transition-opacity"
                style={{
                  background:
                    updateStatus === "has_update"
                      ? "var(--owl-status-warning-bg)"
                      : "var(--owl-status-warning-bg)",
                  borderColor:
                    updateStatus === "has_update"
                      ? "var(--owl-status-warning-border)"
                      : "var(--owl-topbar-pill-border)",
                  color:
                    updateStatus === "has_update"
                      ? "var(--owl-status-warning-fg)"
                      : "var(--owl-topbar-pill-fg)",
                }}
                onClick={handleUpdateBadgeClick}
              >
                {updateStatus === "checking" && <><Loader2 className="h-3 w-3 animate-spin" />Checking...</>}
                {updateStatus === "has_update" && <><CircleCheck className="h-3 w-3" />Update Available</>}
                {(updateStatus === "up_to_date" || updateStatus === "downloaded") && <><CircleCheck className="h-3 w-3" />Up to Date</>}
                {updateStatus === "downloading" && <><Loader2 className="h-3 w-3 animate-spin" />Downloading...</>}
              </Badge>
            )}
            <Badge
              variant="outline"
              className="gap-1 text-[10px]"
              style={{
                background:
                  backendStatus === "connected"
                    ? "var(--owl-status-online-bg)"
                    : backendStatus === "checking"
                      ? "var(--owl-status-warning-bg)"
                      : "var(--owl-status-offline-bg)",
                borderColor:
                  backendStatus === "connected"
                    ? "var(--owl-status-online-border)"
                    : backendStatus === "checking"
                      ? "var(--owl-status-warning-border)"
                      : "var(--owl-status-offline-border)",
                color:
                  backendStatus === "connected"
                    ? "var(--owl-status-online-fg)"
                    : backendStatus === "checking"
                      ? "var(--owl-status-warning-fg)"
                      : "var(--owl-status-offline-fg)",
              }}
            >
              {backendStatus === "checking" && <Loader2 className="h-3 w-3 animate-spin" />}
              {backendStatus === "connected" && <CircleCheck className="h-3 w-3" />}
              {backendStatus === "disconnected" && <CircleX className="h-3 w-3" />}
              {backendStatus === "checking" ? "Connecting..." : backendStatus === "connected" ? "Connected" : "Offline"}
            </Badge>
            <button
              className="rounded-full p-2 transition-colors"
              style={{
                background: "var(--owl-topbar-icon-bg)",
                color: "var(--owl-topbar-icon-fg)",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.background = "var(--owl-topbar-icon-hover-bg)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = "var(--owl-topbar-icon-bg)";
              }}
            >
              <Bell className="h-4 w-4" />
            </button>
            <button
              className="h-8 w-8 rounded-full flex items-center justify-center transition-colors"
              style={{
                background: "var(--owl-avatar-bg)",
                color: "var(--owl-avatar-fg)",
                boxShadow: "inset 0 0 0 1px var(--owl-topbar-pill-border)",
              }}
            >
              <User className="h-4 w-4" />
            </button>
          </div>
        </header>

        {/* ─── Workspace + Data Panel ─── */}
        <div className="flex flex-1 overflow-hidden min-w-0">

          {/* Chat Area */}
          <main className="flex-1 min-w-0 overflow-hidden">
            <ChatArea />
          </main>

          {/* Right Resize Handle (only when expanded) */}
          {!rightCollapsed && <ResizeHandle onDragStart={handleDragStart("right")} />}

          {/* Right Data Panel */}
          <aside
            className="relative shrink-0 transition-[width] duration-200 ease-out"
            style={{ width: effectiveRight }}
          >
            <div className="h-full w-full overflow-hidden">
              {!rightCollapsed && <DataPanel />}
            </div>
            <EdgeChevron side="right" collapsed={rightCollapsed} onClick={toggleRightCollapsed} />
          </aside>
        </div>
      </div>

      {/* Dialogs */}
      <SettingsDialog />
      <DatabaseWarningDialog open={showDatabaseWarning} onClose={() => dismissDatabaseWarning()} />
    </div>
  );
}