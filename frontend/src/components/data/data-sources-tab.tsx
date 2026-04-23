// frontend/src/components/data/data-sources-tab.tsx

"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Database,
  RefreshCw,
  Trash2,
  Clock,
  Rows3,
  Columns3,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Plus,
  Search,
  X,
  Eye,
  GripVertical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchDuckDBTables,
  previewDuckDBTable,
  deleteDuckDBTable,
  addTableToContext,
  fetchKnowledge,
  type DuckDBTableItem,
  syncWarehouseMetadata,
} from "@/lib/api";
import { useTaskStore } from "@/stores/use-task-store";

// ── Drag payload type key ─────────────────────────────────
export const DATASOURCE_DRAG_TYPE = "application/x-owl-datasource";

export default function DataSourcesTab() {
  const [tables, setTables] = useState<DuckDBTableItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { setPreviewData, currentTaskId, addKnowledge } = useTaskStore();

  // ── Search ──────────────────────────────────────────────
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  const filteredTables = useMemo(() => {
    if (!searchQuery.trim()) return tables;
    const q = searchQuery.trim().toLowerCase();
    return tables.filter(
      (t) =>
        t.display_name.toLowerCase().includes(q) ||
        t.table_name.toLowerCase().includes(q) ||
        (t.description && t.description.toLowerCase().includes(q))
    );
  }, [tables, searchQuery]);

  const commitSearch = () => setSearchQuery(searchInput);
  const clearSearch = () => {
    setSearchInput("");
    setSearchQuery("");
  };

  // ── Context menu ────────────────────────────────────────
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    table: DuckDBTableItem;
  } | null>(null);
  const ctxMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!contextMenu) return;
    const close = (e: MouseEvent) => {
      if (ctxMenuRef.current && !ctxMenuRef.current.contains(e.target as Node))
        setContextMenu(null);
    };
    const closeOnEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setContextMenu(null);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", closeOnEsc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", closeOnEsc);
    };
  }, [contextMenu]);

  // ── Data loading ────────────────────────────────────────
  // 替换原有的 loadTables
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
  const handleRefresh = useCallback(async () => {
    setLoading(true);
    try {
      await syncWarehouseMetadata();
      const res = await fetchDuckDBTables();
      setTables(res.data);
    } catch (err) {
      console.error("Failed to sync/load DuckDB tables:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTables();
  }, [loadTables]);

  // ── Actions ─────────────────────────────────────────────
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

  const handleDelete = async (
    e: React.MouseEvent | null,
    table: DuckDBTableItem
  ) => {
    e?.stopPropagation();
    if (!confirm(`Delete table "${table.display_name}"? This cannot be undone.`))
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
    e: React.MouseEvent | null,
    table: DuckDBTableItem
  ) => {
    e?.stopPropagation();
    if (!currentTaskId) return;
    try {
      const res = await addTableToContext(table.id, currentTaskId);
      if (res.data.status === "added" || res.data.status === "already_added") {
        const knowledgeRes = await fetchKnowledge(currentTaskId);
        useTaskStore.getState().setKnowledgeList(knowledgeRes.data);
      }
    } catch (err) {
      console.error("Add to context failed:", err);
    }
  };

  // ── Drag start ──────────────────────────────────────────
  const handleDragStart = (
    e: React.DragEvent<HTMLDivElement>,
    table: DuckDBTableItem
  ) => {
    const payload = JSON.stringify({
      id: table.id,
      display_name: table.display_name,
      table_name: table.table_name,
    });
    e.dataTransfer.setData(DATASOURCE_DRAG_TYPE, payload);
    e.dataTransfer.setData("text/plain", table.display_name);
    e.dataTransfer.effectAllowed = "copy";
  };

  // ── Context menu handler ────────────────────────────────
  const handleContextMenu = (
    e: React.MouseEvent,
    table: DuckDBTableItem
  ) => {
    e.preventDefault();
    e.stopPropagation();
    // Clamp position to stay within viewport
    const x = Math.min(e.clientX, window.innerWidth - 200);
    const y = Math.min(e.clientY, window.innerHeight - 160);
    setContextMenu({ x, y, table });
  };

  // ── Status icon ─────────────────────────────────────────
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

  // ── Empty / loading states ──────────────────────────────
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
      {/* ── Toolbar: Search + Refresh ──────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b">
        <div className="relative flex-1 flex items-center gap-1">
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitSearch();
              if (e.key === "Escape") clearSearch();
            }}
            placeholder="Search by name or description…"
            className="h-7 text-xs pr-7"
          />
          {searchQuery && (
            <button
              onClick={clearSearch}
              className="absolute right-14 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-muted"
              title="Clear search"
            >
              <X className="h-3 w-3 text-muted-foreground" />
            </button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs shrink-0"
            onClick={commitSearch}
          >
            <Search className="h-3 w-3" />
          </Button>
        </div>

        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs shrink-0"
          onClick={handleRefresh}
          disabled={loading}
        >
          <RefreshCw
            className={cn("h-3 w-3 mr-1", loading && "animate-spin")}
          />
          Refresh
        </Button>
      </div>

      {/* Count bar */}
      <div className="px-4 py-1.5 text-[10px] text-muted-foreground border-b">
        {searchQuery ? (
          <>
            {filteredTables.length} of {tables.length} table
            {tables.length > 1 ? "s" : ""} matching &quot;{searchQuery}&quot;
          </>
        ) : (
          <>
            {tables.length} table{tables.length > 1 ? "s" : ""}
          </>
        )}
      </div>

      {/* ── Table list ─────────────────────────────────── */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {filteredTables.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-10 text-muted-foreground">
              <Search className="h-6 w-6 opacity-30" />
              <p className="text-xs">
                No data sources match &quot;{searchQuery}&quot;
              </p>
              <button
                onClick={clearSearch}
                className="text-xs text-primary hover:underline"
              >
                Clear search
              </button>
            </div>
          ) : (
            filteredTables.map((table) => {
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
                  draggable
                  onDragStart={(e) => handleDragStart(e, table)}
                  onContextMenu={(e) => handleContextMenu(e, table)}
                  className={cn(
                    "group relative rounded-lg border p-3 cursor-pointer transition-all",
                    "hover:shadow-sm",
                    selectedId === table.id
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-muted-foreground/30"
                  )}
                  onClick={() => setSelectedId(table.id)}
                >
                  {/* Drag grip hint */}
                  <div className="absolute left-0.5 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-40 transition-opacity">
                    <GripVertical className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>

                  {/* Row 1: Name + Status */}
                  <div className="flex items-center gap-2 pl-3">
                    <Database className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                    <span className="text-sm font-medium truncate flex-1">
                      {table.display_name}
                    </span>
                    {statusIcon(table.status)}
                  </div>

                  {/* Row 2: Table name (monospace) */}
                  <div className="mt-1 pl-3 text-[11px] text-muted-foreground font-mono truncate">
                    {table.table_name}
                  </div>

                  {/* Row 3: Stats */}
                  <div className="mt-2 pl-3 flex items-center gap-3 text-[10px] text-muted-foreground">
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
                    <p className="mt-1.5 pl-3 text-[11px] text-muted-foreground truncate">
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
            })
          )}
        </div>
      </ScrollArea>

      {/* ── Right-click context menu (portal-style) ──── */}
      {contextMenu && (
        <div
          ref={ctxMenuRef}
          className="fixed z-[100] min-w-[180px] rounded-md border bg-popover p-1 shadow-lg animate-in fade-in-0 zoom-in-95"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs hover:bg-accent transition-colors"
            onClick={() => {
              handlePreview(contextMenu.table);
              setContextMenu(null);
            }}
          >
            <Eye className="h-3.5 w-3.5" />
            Preview
          </button>

          {currentTaskId && (
            <button
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs hover:bg-accent transition-colors"
              onClick={() => {
                handleAddToContext(null, contextMenu.table);
                setContextMenu(null);
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              Add to Current Task
            </button>
          )}

          <div className="my-1 h-px bg-border" />

          <button
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs text-destructive hover:bg-destructive/10 transition-colors"
            onClick={() => {
              handleDelete(null, contextMenu.table);
              setContextMenu(null);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </button>
        </div>
      )}
    </div>
  );
}