// owlai/frontend/src/components/sidebar/task-sidebar.tsx

"use client";

import { useEffect, useCallback, useState, useRef, useMemo } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { useTaskStore } from "@/stores/use-task-store";
import { useSettingsStore } from "@/stores/use-settings-store";
import { useBackend } from "@/contexts/backend-context";
import {
  fetchTasks,
  createTask,
  deleteTask,
  renameTask,
  fetchKnowledge,
  fetchChatHistory,
} from "@/lib/api";
import {
  Plus,
  Settings,
  Loader2,
  MoreHorizontal,
  Pencil,
  Trash2,
  HelpCircle,
  BarChart3,
  X,
  ClipboardList,
  FileCode2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  LayoutDashboard,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function TaskSidebar({ onClose }: { onClose?: () => void } = {}) {
  const {
    tasks,
    currentTaskId,
    setTasks,
    setCurrentTaskId,
    addTask,
    removeTask,
    updateTaskTitle,
    setKnowledgeList,
    setSteps,
    setPreviewData,
    defaultRuntime,
    setActiveOverview,
  } = useTaskStore();

  const { isReady: backendReady } = useBackend();

  // Section collapse state
  const [adHocCollapsed, setAdHocCollapsed] = useState(false);
  const [routineCollapsed, setRoutineCollapsed] = useState(false);

  // Context Menu
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const createMenuRef = useRef<HTMLDivElement>(null);

  // Filtered task lists
  const adHocTasks = useMemo(() => tasks.filter((t) => t.task_type === "ad_hoc"), [tasks]);
  const routineTasks = useMemo(
    () => tasks.filter((t) => t.task_type === "routine" || t.task_type === "script"),
    [tasks]
  );
  const pipelineTasks = useMemo(() => tasks.filter((t) => t.task_type === "pipeline"), [tasks]);

  useEffect(() => {
    if (!backendReady) return;
    fetchTasks()
      .then((res) => setTasks(res.data))
      .catch((err) => console.error("Failed to load tasks:", err));
  }, [backendReady, setTasks]);

  useEffect(() => {
    if (!menuOpenId) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpenId(null);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpenId]);

  useEffect(() => {
    if (!createMenuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (createMenuRef.current && !createMenuRef.current.contains(e.target as Node)) setCreateMenuOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [createMenuOpen]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const handleSelect = useCallback(
    async (taskId: string) => {
      if (editingId) return;
      setCurrentTaskId(taskId);
      setPreviewData(null, []);
      setActiveOverview(null);
      try {
        const [kRes, cRes] = await Promise.all([fetchKnowledge(taskId), fetchChatHistory(taskId)]);
        setKnowledgeList(kRes.data);
        setSteps(cRes.data);
      } catch {
        setKnowledgeList([]);
        setSteps([]);
      }
    },
    [editingId, setCurrentTaskId, setKnowledgeList, setSteps, setPreviewData, setActiveOverview]
  );

  const { setPendingTaskSetup } = useTaskStore();

  const handleCreateAdHoc = useCallback(async () => {
    const title = `Task ${tasks.length + 1}`;
    const res = await createTask(title, { task_type: "ad_hoc", execution_backend: defaultRuntime });
    addTask(res.data);
    await handleSelect(res.data.id);
    setCreateMenuOpen(false);
    onClose?.();
  }, [tasks.length, addTask, handleSelect, onClose, defaultRuntime]);

  const handleCreateTypedTask = useCallback(
    async (taskType: "routine" | "script" | "pipeline") => {
      const prefixMap = { routine: "Routine", script: "Script", pipeline: "Pipeline" };
      const res = await createTask(`${prefixMap[taskType]} Task`, { task_type: taskType, execution_backend: defaultRuntime });
      addTask(res.data);
      setPendingTaskSetup({ taskId: res.data.id, taskType });
      await handleSelect(res.data.id);
      setCreateMenuOpen(false);
      onClose?.();
    },
    [addTask, handleSelect, onClose, setPendingTaskSetup, defaultRuntime]
  );

  const handleDelete = async (taskId: string) => {
    setMenuOpenId(null);
    await deleteTask(taskId);
    removeTask(taskId);
    if (currentTaskId === taskId) {
      setKnowledgeList([]);
      setSteps([]);
      setPreviewData(null, []);
    }
  };

  const handleStartRename = (taskId: string, currentTitle: string) => {
    setMenuOpenId(null);
    setEditingId(taskId);
    setEditingTitle(currentTitle);
  };

  const handleSubmitRename = async () => {
    if (!editingId) return;
    const trimmed = editingTitle.trim();
    if (trimmed) {
      try {
        await renameTask(editingId, trimmed);
        updateTaskTitle(editingId, trimmed);
      } catch (err) {
        console.error("Failed to rename:", err);
      }
    }
    setEditingId(null);
    setEditingTitle("");
  };

  const handleCancelRename = () => { setEditingId(null); setEditingTitle(""); };

  const handleMenuToggle = (e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    if (menuOpenId === taskId) { setMenuOpenId(null); return; }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenuPos({ top: rect.bottom + 4, left: Math.max(4, rect.right - 120) });
    setMenuOpenId(taskId);
  };

  const { setSettingsOpen } = useSettingsStore();

  // ── Render a single task item ──
  const renderTaskItem = (task: typeof tasks[0]) => {
    const isActive = currentTaskId === task.id;
    const isEditing = editingId === task.id;
    const iconMap: Record<string, React.ReactElement> = {
      routine: <ClipboardList className="h-4 w-4 shrink-0 mr-2.5 opacity-60" />,
      script: <FileCode2 className="h-4 w-4 shrink-0 mr-2.5 opacity-60" />,
      pipeline: <RefreshCw className="h-4 w-4 shrink-0 mr-2.5 opacity-60" />,
      ad_hoc: <BarChart3 className="h-4 w-4 shrink-0 mr-2.5 opacity-60" />,
    };

    return (
      <div
        key={task.id}
        onClick={() => !isEditing && handleSelect(task.id)}
        className="group flex cursor-pointer items-center rounded-lg px-3 py-2.5 text-sm transition-colors min-w-0"
        style={isActive ? { background: "var(--owl-sidebar-active-bg)", color: "var(--owl-sidebar-active-fg)" } : {}}
        onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
        onMouseLeave={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
      >
        {iconMap[task.task_type] || iconMap.ad_hoc}
        {isEditing ? (
          <input
            ref={editInputRef}
            value={editingTitle}
            onChange={(e) => setEditingTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleSubmitRename(); } else if (e.key === "Escape") handleCancelRename(); }}
            onBlur={handleSubmitRename}
            onClick={(e) => e.stopPropagation()}
            className="min-w-0 flex-1 rounded px-1 py-0.5 text-sm outline-none bg-black/20 text-inherit"
          />
        ) : (
          <div className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{task.title}</span>
          </div>
        )}
        {!isEditing && (
          <Button
            variant="ghost" size="icon"
            className={cn("h-6 w-6 shrink-0 ml-1 opacity-0 transition-opacity group-hover:opacity-100", menuOpenId === task.id && "opacity-100")}
            style={{ color: "inherit" }}
            onClick={(e) => handleMenuToggle(e, task.id)}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    );
  };

  // ── Section header component ──
  const SectionHeader = ({
    label,
    count,
    collapsed,
    onToggle,
    onOverview,
  }: {
    label: string;
    count: number;
    collapsed?: boolean;
    onToggle?: () => void;
    onOverview?: () => void;
  }) => (
    <div className="flex items-center gap-1 px-2 py-1.5">
      {onToggle ? (
        <button onClick={onToggle} className="flex items-center gap-1 flex-1 min-w-0 text-left">
          {collapsed ? <ChevronRight className="h-3 w-3 shrink-0" /> : <ChevronDown className="h-3 w-3 shrink-0" />}
          <span className="text-[10px] font-bold uppercase tracking-wider truncate" style={{ color: "var(--owl-sidebar-muted)" }}>
            {label}
          </span>
          <span className="text-[10px] ml-1" style={{ color: "var(--owl-sidebar-muted)" }}>({count})</span>
        </button>
      ) : (
        <span className="flex-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--owl-sidebar-muted)" }}>
          {label} ({count})
        </span>
      )}
      {onOverview && (
        <button
          onClick={onOverview}
          className="p-1 rounded hover:bg-white/10 transition-colors"
          style={{ color: "var(--owl-sidebar-muted)" }}
          title="View overview"
        >
          <LayoutDashboard className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );

  const contextMenu = menuOpenId && createPortal(
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[120px] rounded-md border bg-popover text-popover-foreground p-1 shadow-md animate-in fade-in-0 zoom-in-95"
      style={{ top: menuPos.top, left: menuPos.left }}
      onClick={(e) => e.stopPropagation()}
    >
      <button className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground transition-colors"
        onClick={() => { const task = tasks.find((t) => t.id === menuOpenId); if (task) handleStartRename(task.id, task.title); }}>
        <Pencil className="h-3.5 w-3.5" /> Rename
      </button>
      <button className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
        onClick={() => handleDelete(menuOpenId)}>
        <Trash2 className="h-3.5 w-3.5" /> Delete
      </button>
    </div>,
    document.body
  );

  return (
    <div className="flex h-full w-full flex-col overflow-hidden"
      style={{ background: "var(--owl-sidebar-bg)", color: "var(--owl-sidebar-fg)", borderRight: "1px solid var(--owl-sidebar-border)" }}>
      {/* Brand */}
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-center gap-2.5">
          {onClose && (
            <button onClick={onClose} className="md:hidden flex h-8 w-8 items-center justify-center rounded-lg hover:opacity-80" style={{ color: "var(--owl-sidebar-muted)" }}>
              <X className="h-5 w-5" />
            </button>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold tracking-tight" style={{ color: "var(--owl-brand-fg)" }}>owl.ai</div>
            <div className="text-[10px] font-medium tracking-widest uppercase" style={{ color: "var(--owl-brand-sub)" }}>Data Engine</div>
          </div>
        </div>
      </div>

      {/* New Analysis Task button */}
      <div className="px-4 pb-4">
        <div className="relative flex w-full" ref={createMenuRef}>
          <Button className="flex-1 justify-center gap-2 rounded-r-none font-semibold"
            style={{ background: "var(--owl-btn-primary-bg)", color: "var(--owl-btn-primary-fg)" }}
            onClick={handleCreateAdHoc} disabled={!backendReady}>
            <Plus className="h-4 w-4" /> New Analysis Task
          </Button>
          <Button className="w-10 rounded-l-none px-0"
            style={{ background: "var(--owl-btn-primary-bg)", color: "var(--owl-btn-primary-fg)", borderLeft: "1px solid color-mix(in srgb, var(--owl-btn-primary-fg) 16%, transparent)" }}
            onClick={() => setCreateMenuOpen((v) => !v)} disabled={!backendReady}>
            <MoreHorizontal className="h-4 w-4" />
          </Button>
          {createMenuOpen && (
            <div className="absolute top-full z-30 mt-2 w-full rounded-xl border p-1.5 shadow-lg"
              style={{ background: "var(--owl-sidebar-bg)", color: "var(--owl-sidebar-fg)", borderColor: "var(--owl-sidebar-border)" }}>
              <button onClick={() => handleCreateTypedTask("routine")}
                className="flex w-full items-start gap-2.5 rounded-md px-3 py-2.5 text-left transition-colors"
                style={{ color: "var(--owl-sidebar-fg)" }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}>
                <ClipboardList className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "var(--owl-sidebar-muted)" }} />
                <div><div className="text-sm font-medium leading-5">Routine Task</div><div className="text-[11px] leading-4" style={{ color: "var(--owl-sidebar-muted)" }}>AI follows a saved SOP</div></div>
              </button>
              <button onClick={() => handleCreateTypedTask("script")}
                className="flex w-full items-start gap-2.5 rounded-md px-3 py-2.5 text-left transition-colors"
                style={{ color: "var(--owl-sidebar-fg)" }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}>
                <FileCode2 className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "var(--owl-sidebar-muted)" }} />
                <div><div className="text-sm font-medium leading-5">Script Task</div><div className="text-[11px] leading-4" style={{ color: "var(--owl-sidebar-muted)" }}>Re-run a saved script</div></div>
              </button>
              <button onClick={() => handleCreateTypedTask("pipeline")}
                className="flex w-full items-start gap-2.5 rounded-md px-3 py-2.5 text-left transition-colors"
                style={{ color: "var(--owl-sidebar-fg)" }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}>
                <RefreshCw className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "var(--owl-sidebar-muted)" }} />
                <div><div className="text-sm font-medium leading-5">Pipeline Task</div><div className="text-[11px] leading-4" style={{ color: "var(--owl-sidebar-muted)" }}>Run a pipeline to update data</div></div>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Task List — grouped sections */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3">
        {!backendReady ? (
          <div className="flex items-center justify-center py-8 text-sm" style={{ color: "var(--owl-sidebar-muted)" }}>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading tasks...
          </div>
        ) : (
          <div className="flex flex-col gap-2 min-w-0">
            {/* Ad-hoc Tasks */}
            <div>
              <SectionHeader label="Ad-hoc Tasks" count={adHocTasks.length} collapsed={adHocCollapsed} onToggle={() => setAdHocCollapsed((v) => !v)} />
              {!adHocCollapsed && (
                <div className="flex flex-col gap-0.5">{adHocTasks.map(renderTaskItem)}</div>
              )}
            </div>

            {/* Routine Tasks */}
            <div>
              <SectionHeader
                label="Routine Tasks"
                count={routineTasks.length}
                collapsed={routineCollapsed}
                onToggle={() => setRoutineCollapsed((v) => !v)}
                onOverview={() => { setActiveOverview("routine"); setCurrentTaskId(null); }}
              />
              {!routineCollapsed && (
                <div className="flex flex-col gap-0.5">{routineTasks.map(renderTaskItem)}</div>
              )}
            </div>

            {/* Data Pipelines — click only, no expand */}
            <div>
              <button
                onClick={() => { setActiveOverview("pipeline"); setCurrentTaskId(null); }}
                className="flex items-center gap-1 px-2 py-1.5 w-full text-left rounded-md transition-colors hover:bg-white/5"
              >
                <RefreshCw className="h-3 w-3 shrink-0" style={{ color: "var(--owl-sidebar-muted)" }} />
                <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--owl-sidebar-muted)" }}>
                  Data Pipelines
                </span>
                <span className="text-[10px] ml-1" style={{ color: "var(--owl-sidebar-muted)" }}>({pipelineTasks.length})</span>
                <LayoutDashboard className="h-3.5 w-3.5 ml-auto" style={{ color: "var(--owl-sidebar-muted)" }} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Bottom actions */}
      <div className="px-3 pb-4 pt-2 flex flex-col gap-1 min-w-0" style={{ borderTop: "1px solid var(--owl-sidebar-border)" }}>
        <button className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors"
          style={{ color: "var(--owl-sidebar-muted)" }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
          onClick={() => setSettingsOpen(true)}>
          <Settings className="h-4 w-4 shrink-0" /><span>Settings</span>
        </button>
        <button className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors"
          style={{ color: "var(--owl-sidebar-muted)" }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--owl-sidebar-hover-bg)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}>
          <HelpCircle className="h-4 w-4 shrink-0" /><span>Documentation</span>
        </button>
      </div>

      {contextMenu}
    </div>
  );
}