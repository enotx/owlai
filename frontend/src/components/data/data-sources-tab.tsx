// frontend/src/components/data/data-sources-tab.tsx

"use client";

import { useEffect, useState, useCallback } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import {
  Database,
  RefreshCw,
  Trash2,
  Clock,
  Rows3,
  Columns3,
  ChevronRight,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchDuckDBTables,
  previewDuckDBTable,
  deleteDuckDBTable,
  addTableToContext,
  type DuckDBTableItem,
} from "@/lib/api";
import { useTaskStore } from "@/stores/use-task-store";

export default function DataSourcesTab() {
  const [tables, setTables] = useState<DuckDBTableItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { setPreviewData, currentTaskId, addKnowledge } = useTaskStore();

  const loadTables = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchDuckDBTables();
      setTables(res.data);
    } catch (err) {
      console.error("Failed to load DuckDB tables:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTables();
  }, [loadTables]);

  const handlePreview = async (table: DuckDBTableItem) => {
    setSelectedId(table.id);
    try {
      const res = await previewDuckDBTable(table.id);
      setPreviewData(res.data.rows, res.data.columns, {
        type: "step",
        dfName: table.display_name,
        stepId: undefined,
      });
    } catch (err) {
      console.error("Preview failed:", err);
    }
  };

  const handleDelete = async (e: React.MouseEvent, table: DuckDBTableItem) => {
    e.stopPropagation();
    if (
      !confirm(
        `Delete table "${table.display_name}"? This cannot be undone.`
      )
    )
      return;
    try {
      await deleteDuckDBTable(table.id);
      setTables((prev) => prev.filter((t) => t.id !== table.id));
      if (selectedId === table.id) setSelectedId(null);
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const handleAddToContext = async (
    e: React.MouseEvent,
    table: DuckDBTableItem
  ) => {
    e.stopPropagation();
    if (!currentTaskId) return;
    try {
      const res = await addTableToContext(table.id, currentTaskId);
      if (res.data.status === "added" || res.data.status === "already_added") {
        // Reload knowledge to refresh the KnowledgeZone
        const { fetchKnowledge } = await import("@/lib/api");
        const knowledgeRes = await fetchKnowledge(currentTaskId);
        useTaskStore.getState().setKnowledgeList(knowledgeRes.data);
      }
    } catch (err) {
      console.error("Add to context failed:", err);
    }
  };

  const statusIcon = (status: string) => {
    switch (status) {
      case "ready":
        return <CheckCircle2 className="h-3 w-3 text-green-500" />;
      case "stale":
        return <AlertCircle className="h-3 w-3 text-amber-500" />;
      case "refreshing":
        return <Loader2 className="h-3 w-3 text-blue-500 animate-spin" />;
      case "error":
        return <AlertCircle className="h-3 w-3 text-red-500" />;
      default:
        return null;
    }
  };

  if (loading && tables.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin opacity-40" />
        <p className="text-sm">Loading data sources...</p>
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground p-6">
        <Database className="h-10 w-10 opacity-30" />
        <p className="text-sm font-medium">No Data Sources Yet</p>
        <p className="text-xs text-center max-w-[240px]">
          Use{" "}
          <code className="bg-muted px-1 rounded text-[11px]">/derive</code> in
          chat to save analysis results as reusable data sources.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b">
        <span className="text-xs text-muted-foreground">
          {tables.length} table{tables.length > 1 ? "s" : ""}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs"
          onClick={loadTables}
          disabled={loading}
        >
          <RefreshCw
            className={cn("h-3 w-3 mr-1", loading && "animate-spin")}
          />
          Refresh
        </Button>
      </div>

      {/* Table list */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {tables.map((table) => {
            const schema = (() => {
              try {
                return JSON.parse(table.table_schema_json) as Array<{
                  name: string;
                  type: string;
                }>;
              } catch {
                return [];
              }
            })();

            return (
              <div
                key={table.id}
                className={cn(
                  "group relative rounded-lg border p-3 cursor-pointer transition-all",
                  "hover:shadow-sm",
                  selectedId === table.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/30"
                )}
                onClick={() => handlePreview(table)}
              >
                {/* Row 1: Name + Status */}
                <div className="flex items-center gap-2">
                  <Database className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                  <span className="text-sm font-medium truncate flex-1">
                    {table.display_name}
                  </span>
                  {statusIcon(table.status)}
                </div>

                {/* Row 2: Table name (monospace) */}
                <div className="mt-1 text-[11px] text-muted-foreground font-mono truncate">
                  {table.table_name}
                </div>

                {/* Row 3: Stats */}
                <div className="mt-2 flex items-center gap-3 text-[10px] text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Rows3 className="h-3 w-3" />
                    {table.row_count.toLocaleString()} rows
                  </span>
                  <span className="flex items-center gap-1">
                    <Columns3 className="h-3 w-3" />
                    {schema.length} cols
                  </span>
                  {table.data_updated_at && (
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(table.data_updated_at).toLocaleDateString()}
                    </span>
                  )}
                </div>

                {/* Row 4: Description */}
                {table.description && (
                  <p className="mt-1.5 text-[11px] text-muted-foreground truncate">
                    {table.description}
                  </p>
                )}

                {/* Hover actions */}
                <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {currentTaskId && (
                    <button
                      className="p-1 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                      onClick={(e) => handleAddToContext(e, table)}
                      title="Add to current task context"
                    >
                      <Plus className="h-3 w-3" />
                    </button>
                  )}
                  <button
                    className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                    onClick={(e) => handleDelete(e, table)}
                    title="Delete table"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}