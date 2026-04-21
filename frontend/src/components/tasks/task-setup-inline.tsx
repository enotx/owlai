// frontend/src/components/tasks/task-setup-inline.tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchAssets,
  fetchDataPipelines,
  updateTask,
  type AssetData,
  type DataPipelineData,
} from "@/lib/api";
import { useTaskStore } from "@/stores/use-task-store";
import {
  Loader2,
  ClipboardList,
  FileCode2,
  RefreshCw,
  Pencil,
  CheckCircle2,
  AlertCircle, Monitor, Server,
} from "lucide-react";

type TypedTaskType = "routine" | "script" | "pipeline";

const TASK_META = {
  routine: {
    label: "Routine Task",
    icon: ClipboardList,
    assetLabel: "Bound SOP",
    emptyText: "No SOP assets available.",
    selectPlaceholder: "Choose an SOP...",
  },
  script: {
    label: "Script Task",
    icon: FileCode2,
    assetLabel: "Bound Script",
    emptyText: "No script assets available.",
    selectPlaceholder: "Choose a script...",
  },
  pipeline: {
    label: "Pipeline Task",
    icon: RefreshCw,
    assetLabel: "Bound Pipeline",
    emptyText: "No pipeline assets available.",
    selectPlaceholder: "Choose a pipeline...",
  },
} satisfies Record<
  TypedTaskType,
  {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    assetLabel: string;
    emptyText: string;
    selectPlaceholder: string;
  }
>;

export default function TaskSetupInline() {
  const {
    currentTaskId,
    tasks,
    pendingTaskSetup,
    setPendingTaskSetup,
    updateTask: updateTaskInStore,
  } = useTaskStore();

  const currentTask = useMemo(
    () => tasks.find((t) => t.id === currentTaskId),
    [tasks, currentTaskId]
  );

  const taskType = currentTask?.task_type;
  const isTypedTask =
    taskType === "routine" || taskType === "script" || taskType === "pipeline";

  const typedTaskType = isTypedTask ? taskType : null;

  const isIncomplete = useMemo(() => {
    if (!currentTask || !typedTaskType) return false;
    if (typedTaskType === "pipeline") return !currentTask.pipeline_id;
    return !currentTask.asset_id;
  }, [currentTask, typedTaskType]);

  const shouldForceEdit =
    !!pendingTaskSetup &&
    pendingTaskSetup.taskId === currentTaskId &&
    pendingTaskSetup.taskType === typedTaskType;

  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [assets, setAssets] = useState<AssetData[]>([]);
  const [pipelines, setPipelines] = useState<DataPipelineData[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!currentTask || !typedTaskType) return;
    setTitle(currentTask.title || "");
    setDescription(currentTask.description || "");
    setSelectedAssetId(
      typedTaskType === "pipeline"
        ? currentTask.pipeline_id || ""
        : currentTask.asset_id || ""
    );
  }, [currentTask, typedTaskType, isEditing]);

  useEffect(() => {
    if (!typedTaskType) return;
    setLoadingAssets(true);

    if (typedTaskType === "pipeline") {
      fetchDataPipelines()
        .then((res) => setPipelines(res.data))
        .catch(() => setPipelines([]))
        .finally(() => setLoadingAssets(false));
      return;
    }

    fetchAssets()
      .then((res) => setAssets(res.data))
      .catch(() => setAssets([]))
      .finally(() => setLoadingAssets(false));
  }, [typedTaskType]);

  useEffect(() => {
    if (!typedTaskType) return;

    if (isIncomplete || shouldForceEdit) {
      setIsEditing(true);
    } else {
      setIsEditing(false);
    }
  }, [isIncomplete, shouldForceEdit, typedTaskType]);

  const filteredAssets = useMemo(() => {
    if (!typedTaskType) return [];
    switch (typedTaskType) {
      case "routine":
        return assets.filter((a) => a.asset_type === "sop");
      case "script":
        return assets.filter(
          (a) => a.asset_type === "script" && a.script_type === "general"
        );
      case "pipeline":
        return assets.filter(
          (a) => a.asset_type === "script" && a.script_type === "pipeline"
        );
    }
  }, [assets, typedTaskType]);

  const filteredPipelines = useMemo(() => {
    if (typedTaskType !== "pipeline") return [];
    return pipelines;
  }, [pipelines, typedTaskType]);

  useEffect(() => {
    if (!selectedAssetId || title.trim()) return;
    if (!typedTaskType) return;

    const selectedName =
      typedTaskType === "pipeline"
        ? filteredPipelines.find((p) => p.id === selectedAssetId)?.name
        : filteredAssets.find((a) => a.id === selectedAssetId)?.name;

    if (!selectedName) return;

    const prefixMap: Record<TypedTaskType, string> = {
      routine: "Routine",
      script: "Script",
      pipeline: "Pipeline",
    };

    setTitle(`${prefixMap[typedTaskType]}: ${selectedName}`);
  }, [selectedAssetId, filteredAssets, filteredPipelines, title, typedTaskType]);

  if (!currentTask || !typedTaskType || !currentTaskId) return null;

  const meta = TASK_META[typedTaskType];
  const Icon = meta.icon;
  const canSave = title.trim() && selectedAssetId;

  const boundName =
    typedTaskType === "pipeline"
      ? filteredPipelines.find((p) => p.id === currentTask.pipeline_id)?.name ||
        "Not configured"
      : filteredAssets.find((a) => a.id === currentTask.asset_id)?.name ||
        "Not configured";

  const handleSave = async () => {
    if (!canSave || saving) return;
    setSaving(true);
    try {
      const res = await updateTask(currentTaskId, {
        title: title.trim(),
        description: description.trim() || undefined,
        asset_id: typedTaskType === "pipeline" ? null : selectedAssetId,
        pipeline_id: typedTaskType === "pipeline" ? selectedAssetId : null,
      });
      updateTaskInStore(currentTaskId, res.data);
      setPendingTaskSetup(null);
      setIsEditing(false);
    } catch (err) {
      console.error("Failed to setup task:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold">{meta.label}</h3>
            <div className="mt-1 flex items-center gap-2 text-xs">
              {isIncomplete ? (
                <>
                  <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                  <span className="text-amber-600 dark:text-amber-400">
                    Setup incomplete
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                  <span className="text-green-600 dark:text-green-400">
                    Ready to run
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        {!isEditing && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsEditing(true)}
          >
            <Pencil className="mr-1.5 h-3.5 w-3.5" />
            Edit
          </Button>
        )}
      </div>

      {isEditing ? (
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Title
            </label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Give this task a clear name"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              {meta.assetLabel}
            </label>

            {loadingAssets ? (
              <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading assets...
              </div>
            ) : typedTaskType === "pipeline" ? (
              filteredPipelines.length === 0 ? (
                <div className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
                  {meta.emptyText}
                </div>
              ) : (
                <Select value={selectedAssetId} onValueChange={setSelectedAssetId}>
                  <SelectTrigger>
                    <SelectValue placeholder={meta.selectPlaceholder} />
                  </SelectTrigger>
                  <SelectContent>
                    {filteredPipelines.map((pipeline) => (
                      <SelectItem key={pipeline.id} value={pipeline.id}>
                        {pipeline.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )
            ) : filteredAssets.length === 0 ? (
              <div className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
                {meta.emptyText}
              </div>
            ) : (
              <Select value={selectedAssetId} onValueChange={setSelectedAssetId}>
                <SelectTrigger>
                  <SelectValue placeholder={meta.selectPlaceholder} />
                </SelectTrigger>
                <SelectContent>
                  {filteredAssets.map((asset) => (
                    <SelectItem key={asset.id} value={asset.id}>
                      {asset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Description
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description"
            />
          </div>

          <div className="flex items-center justify-end gap-2">
            {!isIncomplete && (
              <Button
                variant="outline"
                onClick={() => {
                  setIsEditing(false);
                  setPendingTaskSetup(null);
                }}
                disabled={saving}
              >
                Cancel
              </Button>
            )}
            <Button onClick={handleSave} disabled={!canSave || saving}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="grid gap-3 md:grid-cols-2">
            {/* 现有的 Title 卡片 */}
            <div className="rounded-lg border bg-muted/20 p-3">
              <div className="text-xs text-muted-foreground">Title</div>
              <div className="mt-1 font-medium break-words">{currentTask.title}</div>
            </div>
            {/* 现有的 Asset/Pipeline 卡片 */}
            <div className="rounded-lg border bg-muted/20 p-3">
              <div className="text-xs text-muted-foreground">{meta.assetLabel}</div>
              <div className="mt-1 font-medium break-words">{boundName}</div>
            </div>
            {/* ========== Runtime 卡片 ========== */}
            <div className="rounded-lg border bg-muted/20 p-3">
              <div className="text-xs text-muted-foreground">Runtime</div>
              <div className="mt-1 font-medium break-words flex items-center gap-1.5">
                {(!currentTask.execution_backend || currentTask.execution_backend === "local") ? (
                  <>
                    <Monitor className="h-3.5 w-3.5 text-muted-foreground" />
                    Local Sandbox
                  </>
                ) : (
                  <>
                    <Server className="h-3.5 w-3.5 text-green-600" />
                    {currentTask.execution_backend.replace("jupyter:", "")}
                  </>
                )}
              </div>
            </div>
          </div>
          {/* 现有的 Description 卡片 */}
          <div className="rounded-lg border bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground">Description</div>
            <div className="mt-1 break-words">
              {currentTask.description?.trim() || "No description"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}