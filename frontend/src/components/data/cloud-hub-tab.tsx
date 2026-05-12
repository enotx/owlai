// owlai/frontend/src/components/data/cloud-hub-tab.tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import {
  Cloud,
  RefreshCw,
  Plus,
  Loader2,
  Database,
  Rows3,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchCloudDatasets,
  addCloudDatasetToContext,
  fetchKnowledge,
  type CloudDatasetItem,
} from "@/lib/api";
import { useTaskStore } from "@/stores/use-task-store";

export const CLOUD_DATASET_DRAG_TYPE = "application/x-owl-cloud-dataset";


export default function CloudHubTab() {
  const [datasets, setDatasets] = useState<CloudDatasetItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { currentTaskId } = useTaskStore();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchCloudDatasets();
      setDatasets(res.data);
    } catch (err: unknown) {
      setError("Failed to connect to owl-server");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async (slug: string) => {
    if (!currentTaskId) return;
    try {
      await addCloudDatasetToContext(slug, currentTaskId);
      const knowledgeRes = await fetchKnowledge(currentTaskId);
      useTaskStore.getState().setKnowledgeList(knowledgeRes.data);
    } catch (err) {
      console.error("Failed to add cloud dataset:", err);
    }
  };

  if (loading && datasets.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin opacity-40" />
        <p className="text-sm">Loading cloud datasets...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-muted-foreground">
        <AlertCircle className="h-8 w-8 opacity-40" />
        <p className="text-sm">{error}</p>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3 w-3 mr-1" /> Retry
        </Button>
      </div>
    );
  }

  if (datasets.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-muted-foreground">
        <Cloud className="h-10 w-10 opacity-30" />
        <p className="text-sm">No cloud datasets available</p>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3 w-3 mr-1" /> Refresh
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-xs text-muted-foreground">
          {datasets.length} dataset{datasets.length > 1 ? "s" : ""}
        </span>
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={load} disabled={loading}>
          <RefreshCw className={cn("h-3 w-3 mr-1", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {datasets.map((ds) => (
            <div
              key={ds.slug}
              draggable
              onDragStart={(e) => {
                const payload = JSON.stringify({ slug: ds.slug, name: ds.name });
                e.dataTransfer.setData(CLOUD_DATASET_DRAG_TYPE, payload);
                e.dataTransfer.setData("text/plain", ds.name);
                e.dataTransfer.effectAllowed = "copy";
              }}
              className="group relative rounded-lg border p-3 hover:shadow-sm transition-all cursor-grab active:cursor-grabbing"
            >
              <div className="flex items-center gap-2">
                <Cloud className="h-3.5 w-3.5 text-sky-500 shrink-0" />
                <span className="text-sm font-medium truncate flex-1">{ds.name}</span>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground font-mono">{ds.slug}</div>
              {ds.description && (
                <p className="mt-1 text-[11px] text-muted-foreground truncate">{ds.description}</p>
              )}
              <div className="mt-2 flex items-center gap-3 text-[10px] text-muted-foreground">
                {ds.row_count != null && (
                  <span className="flex items-center gap-1">
                    <Rows3 className="h-3 w-3" />
                    {ds.row_count.toLocaleString()} rows
                  </span>
                )}
              </div>
              {currentTaskId && (
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    className="p-1 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary"
                    onClick={() => handleAdd(ds.slug)}
                    title="Add to current task context"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}