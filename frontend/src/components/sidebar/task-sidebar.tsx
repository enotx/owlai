// frontend/src/components/sidebar/task-sidebar.tsx

"use client";

/**
 * 左侧边栏：Task 列表 + 新建 Task + 设置入口
 * 支持右键/按钮 Context Menu（重命名、删除）
 */
import { useEffect, useCallback, useState, useRef } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
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
  FolderOpen,
  Loader2,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function TaskSidebar() {
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
  } = useTaskStore();

  const { isReady: backendReady } = useBackend();

  // Context Menu 状态
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  // 行内编辑状态
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  /* 后端就绪后加载 Task 列表 */
  useEffect(() => {
    if (!backendReady) return;
    fetchTasks()
      .then((res) => setTasks(res.data))
      .catch((err) => console.error("❌ Failed to load tasks:", err));
  }, [backendReady, setTasks]);

  /* 点击外部关闭 Context Menu */
  useEffect(() => {
    if (!menuOpenId) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpenId]);

  /* 进入编辑模式后自动聚焦 */
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  /* 切换 Task */
  const handleSelect = useCallback(
    async (taskId: string) => {
      if (editingId) return;
      setCurrentTaskId(taskId);
      setPreviewData(null, []);
      try {
        const [kRes, cRes] = await Promise.all([
          fetchKnowledge(taskId),
          fetchChatHistory(taskId),
        ]);
        setKnowledgeList(kRes.data);
        setSteps(cRes.data);
      } catch {
        setKnowledgeList([]);
        setSteps([]);
      }
    },
    [editingId, setCurrentTaskId, setKnowledgeList, setSteps, setPreviewData]
  );

  /* 新建 Task */
  const handleCreate = async () => {
    const title = `Task ${tasks.length + 1}`;
    const res = await createTask(title);
    addTask(res.data);
    await handleSelect(res.data.id);
  };

  /* 删除 Task */
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

  /* 开始重命名 */
  const handleStartRename = (taskId: string, currentTitle: string) => {
    setMenuOpenId(null);
    setEditingId(taskId);
    setEditingTitle(currentTitle);
  };

  /* 提交重命名 */
  const handleSubmitRename = async () => {
    if (!editingId) return;
    const trimmed = editingTitle.trim();
    if (trimmed) {
      try {
        await renameTask(editingId, trimmed);
        updateTaskTitle(editingId, trimmed);
      } catch (err) {
        console.error("Failed to rename task:", err);
      }
    }
    setEditingId(null);
    setEditingTitle("");
  };

  /* 取消重命名 */
  const handleCancelRename = () => {
    setEditingId(null);
    setEditingTitle("");
  };

  /* 打开 Context Menu，基于按钮位置计算 fixed 坐标 */
  const handleMenuToggle = (e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    if (menuOpenId === taskId) {
      setMenuOpenId(null);
    } else {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      setMenuPos({
        top: rect.bottom + 4,
        left: Math.max(4, rect.right - 120),
      });
      setMenuOpenId(taskId);
    }
  };

  const { setSettingsOpen } = useSettingsStore();

  /* Context Menu 通过 Portal 渲染到 body，用 fixed 定位，不受父级 overflow 影响 */
  const contextMenu =
    menuOpenId &&
    createPortal(
      <div
        ref={menuRef}
        className="fixed z-50 min-w-[120px] rounded-md border bg-popover text-popover-foreground p-1 shadow-md animate-in fade-in-0 zoom-in-95"
        style={{ top: menuPos.top, left: menuPos.left }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground transition-colors"
          onClick={() => {
            const task = tasks.find((t) => t.id === menuOpenId);
            if (task) handleStartRename(task.id, task.title);
          }}
        >
          <Pencil className="h-3.5 w-3.5" />
          Rename
        </button>
        <button
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
          onClick={() => handleDelete(menuOpenId)}
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </button>
      </div>,
      document.body
    );

  return (
    <div className="flex h-full w-full flex-col border-r bg-muted/30 overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center gap-2 px-4 py-3">
        <FolderOpen className="h-5 w-5 text-primary shrink-0" />
        <h2 className="text-sm font-semibold tracking-tight truncate">Task History</h2>
      </div>
      <Separator />

      {/* Task 列表 */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-2">
        {!backendReady ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading tasks...
          </div>
        ) : (
          <div className="flex flex-col gap-1 min-w-0">
            {tasks.map((task) => {
              const isActive = currentTaskId === task.id;
              const isEditing = editingId === task.id;

              return (
                <div
                  key={task.id}
                  onClick={() => !isEditing && handleSelect(task.id)}
                  className={cn(
                    "group flex cursor-pointer items-center rounded-md px-3 py-2 text-sm transition-colors min-w-0",
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-accent hover:text-accent-foreground"
                  )}
                >
                  {isEditing ? (
                    <input
                      ref={editInputRef}
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          handleSubmitRename();
                        } else if (e.key === "Escape") {
                          handleCancelRename();
                        }
                      }}
                      onBlur={handleSubmitRename}
                      onClick={(e) => e.stopPropagation()}
                      className={cn(
                        "min-w-0 flex-1 rounded px-1 py-0.5 text-sm outline-none",
                        isActive
                          ? "bg-primary-foreground/20 text-primary-foreground placeholder:text-primary-foreground/50"
                          : "bg-background text-foreground border border-input"
                      )}
                    />
                  ) : (
                    <span className="min-w-0 flex-1 truncate">{task.title}</span>
                  )}

                  {!isEditing && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        "h-6 w-6 shrink-0 ml-1 opacity-0 transition-opacity group-hover:opacity-100",
                        menuOpenId === task.id && "opacity-100",
                        isActive
                          ? "hover:bg-primary-foreground/20 text-primary-foreground"
                          : "hover:bg-accent text-muted-foreground"
                      )}
                      onClick={(e) => handleMenuToggle(e, task.id)}
                    >
                      <MoreHorizontal className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 底部操作区 */}
      <div className="px-3 pb-3 pt-1 flex flex-col gap-2 min-w-0">
        <Button
          variant="outline"
          className="w-full justify-start gap-2 min-w-0"
          onClick={handleCreate}
          disabled={!backendReady}
        >
          <Plus className="h-4 w-4 shrink-0" />
          <span className="truncate">New Task</span>
        </Button>
        <Separator />
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 text-muted-foreground min-w-0"
          onClick={() => setSettingsOpen(true)}
        >
          <Settings className="h-4 w-4 shrink-0" />
          <span className="truncate">Settings</span>
        </Button>
      </div>

      {/* Context Menu Portal */}
      {contextMenu}
    </div>
  );
}