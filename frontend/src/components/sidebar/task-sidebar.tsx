// frontend/src/components/sidebar/task-sidebar.tsx

"use client";

/**
 * 左侧边栏：Task 列表 + 新建 Task + 设置入口
 */
import { useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useTaskStore } from "@/stores/use-task-store";
import { useSettingsStore } from "@/stores/use-settings-store";
import {
  fetchTasks,
  createTask,
  deleteTask,
  fetchKnowledge,
  fetchChatHistory,
} from "@/lib/api";
import { Plus, Trash2, Settings, FolderOpen } from "lucide-react";
import { cn } from "@/lib/utils";

export default function TaskSidebar() {
  const {
    tasks,
    currentTaskId,
    setTasks,
    setCurrentTaskId,
    addTask,
    removeTask,
    setKnowledgeList,
    setSteps,
    setPreviewData,
  } = useTaskStore();

  /* 初始化加载 Task 列表 */
  useEffect(() => {
    fetchTasks().then((res) => setTasks(res.data));
  }, [setTasks]);

  /* 切换 Task —— 同时加载 Knowledge 和 Chat 历史 */
  const handleSelect = useCallback(
    async (taskId: string) => {
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
    [setCurrentTaskId, setKnowledgeList, setSteps, setPreviewData]
  );

  /* 新建 Task */
  const handleCreate = async () => {
    const title = `Task ${tasks.length + 1}`;
    const res = await createTask(title);
    addTask(res.data);
    await handleSelect(res.data.id);
  };

  /* 删除 Task */
  const handleDelete = async (e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    await deleteTask(taskId);
    removeTask(taskId);
    if (currentTaskId === taskId) {
      setKnowledgeList([]);
      setSteps([]);
      setPreviewData(null, []);
    }
  };

  // 设置入口
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
        <div className="flex flex-col gap-1">
          {tasks.map((task) => (
            <div
              key={task.id}
              onClick={() => handleSelect(task.id)}
              className={cn(
                "group flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm transition-colors",
                currentTaskId === task.id
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <span className="truncate">{task.title}</span>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100",
                  currentTaskId === task.id
                    ? "hover:bg-primary-foreground/20 text-primary-foreground"
                    : "hover:bg-destructive/10 text-muted-foreground"
                )}
                onClick={(e) => handleDelete(e, task.id)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      </ScrollArea>

      {/* 底部操作区 */}
      <div className="px-3 pb-3 pt-1 flex flex-col gap-2">
        <Button variant="outline" className="w-full justify-start gap-2" onClick={handleCreate}>
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