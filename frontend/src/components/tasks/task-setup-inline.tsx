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
import { Loader2, ClipboardList, FileCode2, RefreshCw } from "lucide-react";

type TypedTaskType = "routine" | "script" | "pipeline";

const TASK_META = {
  routine: {
    label: "Routine Task Setup",
    icon: ClipboardList,
    assetLabel: "Select SOP",
    emptyText: "No SOP assets available.",
  },
  script: {
    label: "Script Task Setup",
    icon: FileCode2,
    assetLabel: "Select Script",
    emptyText: "No script assets available.",
  },
  pipeline: {
    label: "Pipeline Task Setup",
    icon: RefreshCw,
    assetLabel: "Select Pipeline",
    emptyText: "No pipeline assets available.",
  },
} satisfies Record<
  TypedTaskType,
  {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    assetLabel: string;
    emptyText: string;
  }
>;

export default function TaskSetupInline() {
  const {
    currentTaskId,
    tasks,
    pendingTaskSetup,
    setPendingTaskSetup,
  } = useTaskStore();

  const currentTask = useMemo(
    () => tasks.find((t) => t.id === currentTaskId),
    [tasks, currentTaskId]
  );

  const setup =
    pendingTaskSetup && pendingTaskSetup.taskId === currentTaskId
      ? pendingTaskSetup
      : null;

  const taskType = setup?.taskType;

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [assets, setAssets] = useState<AssetData[]>([]);
  const [pipelines, setPipelines] = useState<DataPipelineData[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!setup || !currentTask) return;
    setTitle(currentTask.title || "");
    setDescription(currentTask.description || "");
    setSelectedAssetId(
      taskType === "pipeline"
        ? currentTask.pipeline_id || ""
        : currentTask.asset_id || ""
    );
  }, [setup, currentTask]);

  useEffect(() => {
    if (!setup) return;
    setLoadingAssets(true);
    if (setup.taskType === "pipeline") {
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
  }, [setup]);

  const filteredAssets = useMemo(() => {
    if (!taskType) return [];
    switch (taskType) {
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
  }, [assets, taskType]);
  
  const filteredPipelines = useMemo(() => {
    if (taskType !== "pipeline") return [];
    return pipelines;
  }, [pipelines, taskType]);

  useEffect(() => {
    if (!selectedAssetId || title.trim()) return;
    const selectedName =
      taskType === "pipeline"
        ? filteredPipelines.find((p) => p.id === selectedAssetId)?.name
        : filteredAssets.find((a) => a.id === selectedAssetId)?.name;
    if (!selectedName || !taskType) return;

    const prefixMap: Record<TypedTaskType, string> = {
      routine: "Routine",
      script: "Script",
      pipeline: "Pipeline",
    };

    setTitle(`${prefixMap[taskType]}: ${selectedName}`);
  }, [selectedAssetId, filteredAssets, filteredPipelines, title, taskType]);

  if (!setup || !taskType || !currentTaskId) return null;

  const meta = TASK_META[taskType];
  const Icon = meta.icon;
  const canSave = title.trim() && selectedAssetId;

  const handleSave = async () => {
    if (!canSave || saving) return;
    setSaving(true);
    try {
      const res = await updateTask(currentTaskId, {
        title: title.trim(),
        description: description.trim() || undefined,
        asset_id: taskType === "pipeline" ? undefined : selectedAssetId,
        pipeline_id: taskType === "pipeline" ? selectedAssetId : undefined,
      });

      useTaskStore.setState((state) => ({
        tasks: state.tasks.map((task) =>
          task.id === currentTaskId ? res.data : task
        ),
      }));

      setPendingTaskSetup(null);
    } catch (err) {
      console.error("Failed to setup task:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold">{meta.label}</h3>
          <p className="text-xs text-muted-foreground">
            Complete the configuration before execution.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Title</label>
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
          ) : taskType === "pipeline" ? (
            filteredPipelines.length === 0 ? (
              <div className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
                {meta.emptyText}
              </div>
            ) : (
              <Select value={selectedAssetId} onValueChange={setSelectedAssetId}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a pipeline..." />
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
                <SelectValue placeholder="Choose an asset..." />
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
          <Button
            variant="outline"
            onClick={() => setPendingTaskSetup(null)}
            disabled={saving}
          >
            Later
          </Button>
          <Button onClick={handleSave} disabled={!canSave || saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save Setup
          </Button>
        </div>
      </div>
    </div>
  );
}