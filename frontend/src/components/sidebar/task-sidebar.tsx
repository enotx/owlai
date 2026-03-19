// frontend/src/components/sidebar/task-sidebar.tsx

"use client";

/**
 * 左侧边栏：Task 列表 + 新建 Task + 设置入口
 * 支持右键/按钮 Context Menu（重命名、删除）
 */
import { useEffect, useCallback, useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
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
      if (editingId) return; // 编辑中不切换
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

  const { setSettingsOpen } = useSettingsStore();

  return (
    <div className="flex h-full w-full flex-col border-r bg-muted/30">
      {/* 头部 */}
      <div className="flex items-center gap-2 px-4 py-3">
        <FolderOpen className="h-5 w-5 text-primary" />
        <h2 className="text-sm font-semibold tracking-tight">Task History</h2>
      </div>
      <Separator />

      {/* Task 列表 */}
      <ScrollArea className="flex-1 px-2 py-2">
        {!backendReady ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading tasks...
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {tasks.map((task) => {
              const isActive = currentTaskId === task.id;
              const isEditing = editingId === task.id;

              return (
                <div
                  key={task.id}
                  onClick={() => !isEditing && handleSelect(task.id)}
                  className={cn(
                    "group relative flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-accent hover:text-accent-foreground"
                  )}
                >
                  {/* 标题 / 编辑输入框 */}
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
                        "w-full rounded px-1 py-0.5 text-sm outline-none",
                        isActive
                          ? "bg-primary-foreground/20 text-primary-foreground placeholder:text-primary-foreground/50"
                          : "bg-background text-foreground border border-input"
                      )}
                    />
                  ) : (
                    <span className="truncate pr-2">{task.title}</span>
                  )}

                  {/* "..." 菜单按钮 */}
                  {!isEditing && (
                    <div className="relative shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className={cn(
                          "h-6 w-6 opacity-0 transition-opacity group-hover:opacity-100",
                          menuOpenId === task.id && "opacity-100",
                          isActive
                            ? "hover:bg-primary-foreground/20 text-primary-foreground"
                            : "hover:bg-accent text-muted-foreground"
                        )}
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpenId(
                            menuOpenId === task.id ? null : task.id
                          );
                        }}
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" />
                      </Button>

                      {/* Context Menu 下拉 */}
                      {menuOpenId === task.id && (
                        <div
                          ref={menuRef}
                          className="absolute right-0 top-7 z-50 min-w-[120px] rounded-md border bg-popover text-popover-foreground p-1 shadow-md animate-in fade-in-0 zoom-in-95"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground transition-colors"
                            onClick={() =>
                              handleStartRename(task.id, task.title)
                            }
                          >
                            <Pencil className="h-3.5 w-3.5" />
                            Rename
                          </button>
                          <button
                            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                            onClick={() => handleDelete(task.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </ScrollArea>

      {/* 底部操作区 */}
      <div className="px-3 pb-3 pt-1 flex flex-col gap-2">
        <Button
          variant="outline"
          className="w-full justify-start gap-2"
          onClick={handleCreate}
          disabled={!backendReady}
        >
          <Plus className="h-4 w-4" />
          New Task
        </Button>
        <Separator />
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 text-muted-foreground"
          onClick={() => setSettingsOpen(true)}
        >
          <Settings className="h-4 w-4" />
          Settings
        </Button>
      </div>
    </div>
  );
}