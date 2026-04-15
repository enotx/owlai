// frontend/src/components/tasks/task-create-dialog.tsx

"use client";

import { useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  MessageSquare,
  FileCode2,
  RefreshCw,
  ClipboardList,
  Loader2,
} from "lucide-react";
import { useTaskStore, type Task } from "@/stores/use-task-store";
import {
  createTask,
  fetchAssets,
  fetchKnowledge,
  fetchChatHistory,
  type AssetData,
} from "@/lib/api";

type TaskType = "ad_hoc" | "script" | "pipeline" | "routine";

interface TaskTypeOption {
  value: TaskType;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  requiresAsset: boolean;
}

const TASK_TYPES: TaskTypeOption[] = [
  {
    value: "ad_hoc",
    label: "Ad-hoc Analysis",
    description: "Free-form data exploration with AI",
    icon: MessageSquare,
    requiresAsset: false,
  },
  {
    value: "routine",
    label: "Routine Analysis",
    description: "AI follows a saved SOP to analyze data",
    icon: ClipboardList,
    requiresAsset: true,
  },
  {
    value: "script",
    label: "Script Replay",
    description: "Re-run a saved script on data",
    icon: FileCode2,
    requiresAsset: true,
  },
  {
    value: "pipeline",
    label: "Pipeline Execution",
    description: "Run a pipeline script to update data",
    icon: RefreshCw,
    requiresAsset: true,
  },
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (task: Task) => void;
}

export default function TaskCreateDialog({
  open,
  onOpenChange,
  onCreated,
}: Props) {
  const [taskType, setTaskType] = useState<TaskType>("ad_hoc");
  const [title, setTitle] = useState("");
  const [selectedAssetId, setSelectedAssetId] = useState<string>("");
  const [allAssets, setAllAssets] = useState<AssetData[]>([]);
  const [creating, setCreating] = useState(false);

  const { addTask, setCurrentTaskId, setKnowledgeList, setSteps, setPreviewData } =
    useTaskStore();

  // 加载 assets
  useEffect(() => {
    if (!open) return;
    fetchAssets()
      .then((res) => setAllAssets(res.data))
      .catch(() => setAllAssets([]));
  }, [open]);

  // 重置表单
  useEffect(() => {
    if (open) {
      setTaskType("ad_hoc");
      setTitle("");
      setSelectedAssetId("");
    }
  }, [open]);

  // 根据 taskType 过滤可选 asset
  const filteredAssets = useMemo(() => {
    switch (taskType) {
      case "routine":
        return allAssets.filter((a) => a.asset_type === "sop");
      case "script":
        return allAssets.filter(
          (a) => a.asset_type === "script" && a.script_type === "general"
        );
      case "pipeline":
        return allAssets.filter(
          (a) => a.asset_type === "script" && a.script_type === "pipeline"
        );
      default:
        return [];
    }
  }, [taskType, allAssets]);

  // 当 asset 被选中时自动填充 title
  useEffect(() => {
    if (selectedAssetId && !title) {
      const asset = allAssets.find((a) => a.id === selectedAssetId);
      if (asset) {
        const prefixMap: Record<string, string> = {
          routine: "Routine",
          script: "Script",
          pipeline: "Pipeline",
        };
        setTitle(`${prefixMap[taskType] || "Task"}: ${asset.name}`);
      }
    }
  }, [selectedAssetId, allAssets, taskType, title]);

  const currentTypeInfo = TASK_TYPES.find((t) => t.value === taskType);
  const canCreate =
    title.trim() &&
    (!currentTypeInfo?.requiresAsset || selectedAssetId);

  const handleCreate = async () => {
    if (!canCreate || creating) return;
    setCreating(true);
    try {
      const res = await createTask(title.trim(), {
        task_type: taskType,
        asset_id: selectedAssetId || undefined,
        data_source_ids: [], // 本期先空，后续支持选择
      });
      const newTask = res.data;
      addTask(newTask);
      setCurrentTaskId(newTask.id);
      setPreviewData(null, []);

      // 加载新 task 的空数据
      try {
        const [kRes, cRes] = await Promise.all([
          fetchKnowledge(newTask.id),
          fetchChatHistory(newTask.id),
        ]);
        setKnowledgeList(kRes.data);
        setSteps(cRes.data);
      } catch {
        setKnowledgeList([]);
        setSteps([]);
      }

      onCreated?.(newTask);
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to create task:", err);
    } finally {
      setCreating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Create New Task</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Task Type 选择 */}
          <div className="grid grid-cols-2 gap-2">
            {TASK_TYPES.map((opt) => {
              const Icon = opt.icon;
              const isSelected = taskType === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => {
                    setTaskType(opt.value);
                    setSelectedAssetId("");
                  }}
                  className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors ${
                    isSelected
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border hover:border-muted-foreground/30 hover:bg-muted/50"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium">{opt.label}</span>
                  </div>
                  <span className="text-[11px] text-muted-foreground leading-tight">
                    {opt.description}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Asset 选择（非 ad_hoc 时显示） */}
          {currentTypeInfo?.requiresAsset && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {taskType === "routine"
                  ? "Select SOP"
                  : "Select Script"}
              </label>
              {filteredAssets.length === 0 ? (
                <div className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
                  No {taskType === "routine" ? "SOPs" : "scripts"} available.
                  <br />
                  Create one first using <code>/sop</code> or <code>/script</code> commands.
                </div>
              ) : (
                <Select
                  value={selectedAssetId}
                  onValueChange={setSelectedAssetId}
                >
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue placeholder="Choose an asset..." />
                  </SelectTrigger>
                  <SelectContent>
                    {filteredAssets.map((asset) => (
                      <SelectItem key={asset.id} value={asset.id}>
                        <div className="flex flex-col">
                          <span>{asset.name}</span>
                          {asset.description && (
                            <span className="text-[10px] text-muted-foreground">
                              {asset.description}
                            </span>
                          )}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          {/* Title */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Title
            </label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={`Task ${useTaskStore.getState().tasks.length + 1}`}
              className="h-9"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleCreate();
                }
              }}
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={creating}
          >
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={!canCreate || creating}>
            {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}