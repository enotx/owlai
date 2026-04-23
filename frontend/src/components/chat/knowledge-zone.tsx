// frontend/src/components/chat/knowledge-zone.tsx

"use client";

import { useRef, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { useTaskStore } from "@/stores/use-task-store";
import { uploadKnowledge } from "@/lib/api";
import {
  X,
  FileSpreadsheet,
  FileText,
  Sheet,
  Database,
  Settings,
  Layers,
  Code2,
  ClipboardList,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  addTableToContext,
  addAssetToContext,
  addPipelineToContext,
  fetchKnowledge,
} from "@/lib/api";
import { DATASOURCE_DRAG_TYPE } from "@/components/data/data-sources-tab";
import { ASSET_DRAG_TYPE, PIPELINE_DRAG_TYPE } from "@/components/data/asset-panel";

export default function KnowledgeZone() {
  const { currentTaskId, knowledgeList, addKnowledge, removeKnowledge, setPreviewData } = useTaskStore();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragSource, setDragSource] = useState<"file" | "datasource" | "asset" | "pipeline" | null>(null);
  const dragCounterRef = useRef(0);
  const COLLAPSE_THRESHOLD = 2;
  const [isCollapsed, setIsCollapsed] = useState(true);
  const shouldCollapse = knowledgeList.length > COLLAPSE_THRESHOLD;
  const visibleItems = shouldCollapse && isCollapsed
    ? knowledgeList.slice(0, COLLAPSE_THRESHOLD)
    : knowledgeList;
  const hiddenCount = knowledgeList.length - COLLAPSE_THRESHOLD;

  const processFile = useCallback(async (file: File) => {
    if (!currentTaskId) return;
    const allowedExts = [".csv", ".txt", ".md", ".xlsx", ".xls"];
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExts.includes(ext)) {
      console.warn(`Unsupported file type: ${ext}`);
      return;
    }

    const duplicate = knowledgeList.find(
      (k) => k.name.toLowerCase() === file.name.toLowerCase()
    );
    if (duplicate) {
      alert(`File "${file.name}" already exists in this task. Please rename or delete the existing one first.`);
      return;
    }

    try {
      const res = await uploadKnowledge(currentTaskId, file);
      addKnowledge(res.data);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
        if (axiosErr.response?.status === 409) {
          alert(axiosErr.response.data?.detail || `File "${file.name}" already exists.`);
          return;
        }
      }
      console.error("Upload failed:", err);
    }
  }, [currentTaskId, addKnowledge, knowledgeList]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await processFile(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    const types = e.dataTransfer.types;
    if (types.includes(PIPELINE_DRAG_TYPE)) {
      setIsDragging(true);
      setDragSource("pipeline");
    } else if (types.includes(ASSET_DRAG_TYPE)) {
      setIsDragging(true);
      setDragSource("asset");
    } else if (types.includes(DATASOURCE_DRAG_TYPE)) {
      setIsDragging(true);
      setDragSource("datasource");
    } else if (types.includes("Files")) {
      setIsDragging(true);
      setDragSource("file");
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current--;
      if (dragCounterRef.current === 0) {
        setIsDragging(false);
        setDragSource(null);
      }
    }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    setDragSource(null);
    dragCounterRef.current = 0;

    if (!currentTaskId) return;

    // ── Pipeline drop ─────────────────────────────
    const pipelinePayload = e.dataTransfer.getData(PIPELINE_DRAG_TYPE);
    if (pipelinePayload) {
      try {
        const { id } = JSON.parse(pipelinePayload) as { id: string; name: string };
        await addPipelineToContext(currentTaskId, id);
        const knowledgeRes = await fetchKnowledge(currentTaskId);
        useTaskStore.getState().setKnowledgeList(knowledgeRes.data);
      } catch (err) {
        console.error("Failed to add pipeline to context:", err);
      }
      return;
    }

    // ── Asset drop ────────────────────────────────
    const assetPayload = e.dataTransfer.getData(ASSET_DRAG_TYPE);
    if (assetPayload) {
      try {
        const { id } = JSON.parse(assetPayload) as { id: string; name: string; asset_type: string };
        await addAssetToContext(currentTaskId, id);
        const knowledgeRes = await fetchKnowledge(currentTaskId);
        useTaskStore.getState().setKnowledgeList(knowledgeRes.data);
      } catch (err) {
        console.error("Failed to add asset to context:", err);
      }
      return;
    }

    // ── Data source drop ──────────────────────────
    const dsPayload = e.dataTransfer.getData(DATASOURCE_DRAG_TYPE);
    if (dsPayload) {
      try {
        const { id } = JSON.parse(dsPayload) as {
          id: string;
          display_name: string;
          table_name: string;
        };
        const res = await addTableToContext(id, currentTaskId);
        if (res.data.status === "added" || res.data.status === "already_added") {
          const knowledgeRes = await fetchKnowledge(currentTaskId);
          useTaskStore.getState().setKnowledgeList(knowledgeRes.data);
        }
      } catch (err) {
        console.error("Failed to add data source to context:", err);
      }
      return;
    }

    // ── File drop ─────────────────────────────────
    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await processFile(file);
    }
  }, [processFile, currentTaskId]);

  const handleRemove = async (id: string) => {
    try {
      const { deleteKnowledge: delApi } = await import("@/lib/api");
      await delApi(id);
      removeKnowledge(id);
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const handlePreview = async (k: (typeof knowledgeList)[0]) => {
    try {
      // ── DuckDB table knowledge: use warehouse preview API ──
      if (k.type === "duckdb_table" || k.type === "data_source") {
        let tableId: string | null = null;
        let meta: Record<string, unknown> | null = null;
        if (k.metadata_json) {
          try {
            meta = JSON.parse(k.metadata_json);
            tableId = (meta?.duckdb_table_id as string) ?? null;
          } catch { /* ignore */ }
        }

        if (tableId) {
          const { previewDuckDBTable } = await import("@/lib/api");
          try {
            const res = await previewDuckDBTable(tableId);
            setPreviewData(res.data.rows, res.data.columns, {
              type: "knowledge",
              name: (meta?.display_name as string) || k.name,
              fileType: "excel",
            });
            return;
          } catch {
            // DuckDB preview failed — fall through to metadata display
          }
        }

        // Fallback: render metadata as text preview
        if (meta) {
          const schema = (meta.schema as Array<{ name: string; type: string }>) || [];
          const lines = [
            `# Data Source: ${(meta.display_name as string) || k.name}`,
            meta.description ? `\n${meta.description}` : "",
            `\n**Table:** \`${(meta.table_name as string) || k.name}\``,
            `**Rows:** ${((meta.row_count as number) ?? 0).toLocaleString()}`,
            `**Source:** ${(meta.source_type as string) || "unknown"}`,
            meta.data_updated_at ? `**Updated:** ${meta.data_updated_at}` : "",
            schema.length ? "\n## Schema" : "",
            ...schema.map((c) => `- \`${c.name}\` — ${c.type}`),
          ]
            .filter(Boolean)
            .join("\n");

          setPreviewData([], [], {
            type: "knowledge",
            name: k.name,
            fileType: "text",
            textContent: lines,
          });
        }
        return;
      }

      // ── File-based knowledge (csv / excel / text) ──
      const { previewKnowledge } = await import("@/lib/api");
      const res = await previewKnowledge(k.id);
      const data = res.data;
      if (data.type === "text") {
        setPreviewData([], [], {
          type: "knowledge", name: k.name, fileType: "text", textContent: data.content,
        });
      } else {
        setPreviewData(data.rows, data.columns, {
          type: "knowledge", name: k.name, fileType: data.type,
          availableSheets: data.available_sheets, currentSheet: data.current_sheet, knowledgeId: k.id,
        });
      }
    } catch (err) {
      console.error("Preview failed:", err);
    }
  };

  if (!currentTaskId) return null;

  const getFileIcon = (type: string) => {
    if (type === "csv") return <FileSpreadsheet className="h-5 w-5 text-green-600" />;
    if (type === "excel") return <Sheet className="h-5 w-5 text-blue-600" />;
    if (type === "data_source" || type === "duckdb_table") return <Database className="h-5 w-5 text-emerald-600" />;
    if (type === "asset_script") return <Code2 className="h-5 w-5 text-violet-600" />;
    if (type === "asset_sop") return <ClipboardList className="h-5 w-5 text-amber-600" />;
    if (type === "data_pipeline") return <Layers className="h-5 w-5 text-sky-600" />;
    return <FileText className="h-5 w-5 text-gray-500" />;
  };

  const getFileMeta = (k: (typeof knowledgeList)[0]) => {
    if (k.type === "data_source" || k.type === "duckdb_table") return "Data Source";
    if (k.type === "asset_script") return "Script Asset";
    if (k.type === "asset_sop") return "SOP Asset";
    if (k.type === "data_pipeline") return "Data Pipeline";
    const ext = k.name.slice(k.name.lastIndexOf(".")).toLowerCase();
    if (ext === ".csv") return "CSV Data";
    if (ext === ".xlsx" || ext === ".xls") return "Excel Sheet";
    if (ext === ".md") return "Markdown";
    return "Text File";
  };

  return (
    <div
      className={`rounded-xl border-2 border-dashed p-4 transition-colors ${
        isDragging && dragSource === "datasource"
          ? "border-emerald-500 bg-emerald-500/5"
          : isDragging
            ? "border-primary bg-primary/5"
            : ""
      }`}
      style={{
        borderColor: isDragging ? undefined : "var(--owl-dropzone-border)",
        background: isDragging ? undefined : "var(--owl-dropzone-bg)",
      }}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* File cards — collapsible */}
      {knowledgeList.length > 0 && (
        <div className="mb-3">
          <div className="flex flex-wrap items-center gap-2">
            <div
              className={cn(
                "flex flex-wrap items-center gap-2",
                shouldCollapse && !isCollapsed && "max-h-[160px] overflow-y-auto pr-1"
              )}
            >
              {visibleItems.map((k) => (
                <div
                  key={k.id}
                  className={cn(
                    "group relative flex items-center gap-2 rounded-lg border bg-card cursor-pointer hover:shadow-sm transition-shadow",
                    shouldCollapse && isCollapsed
                      ? "px-2 py-1.5"
                      : "px-3 py-2.5"
                  )}
                  onClick={() => handlePreview(k)}
                >
                  {getFileIcon(k.type)}
                  <div className="min-w-0">
                    <div
                      className={cn(
                        "font-medium truncate",
                        shouldCollapse && isCollapsed
                          ? "text-xs max-w-[100px]"
                          : "text-sm max-w-[140px]"
                      )}
                    >
                      {k.name}
                    </div>
                    {!(shouldCollapse && isCollapsed) && (
                      <div className="text-[10px] text-muted-foreground">
                        {getFileMeta(k)}
                      </div>
                    )}
                  </div>
                  <button
                    className="ml-0.5 rounded-full p-0.5 opacity-0 group-hover:opacity-100 hover:bg-muted-foreground/20 transition-all"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRemove(k.id);
                    }}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}

              {/* Collapse / Expand toggle */}
              {shouldCollapse && (
                <button
                  onClick={() => setIsCollapsed((v) => !v)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-lg border border-dashed px-2.5 py-1.5 text-xs text-muted-foreground",
                    "hover:bg-muted/60 hover:text-foreground transition-colors"
                  )}
                >
                  {isCollapsed ? (
                    <>
                      <span>+{hiddenCount} more</span>
                      <ChevronDown className="h-3 w-3" />
                    </>
                  ) : (
                    <>
                      <span>Show less</span>
                      <ChevronUp className="h-3 w-3" />
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Drop zone prompt */}
      <div
        className="flex items-center justify-center gap-4 text-muted-foreground cursor-pointer"
        onClick={() => fileInputRef.current?.click()}
      >
        <Database className="h-4 w-4 opacity-40" />
        <Settings className="h-4 w-4 opacity-40" />
        <Layers className="h-4 w-4 opacity-40" />
        <span className="text-xs">
          {isDragging && dragSource === "datasource"
            ? "Drop data source to add to context"
            : isDragging && dragSource === "asset"
              ? "Drop asset to add to context"
              : isDragging && dragSource === "pipeline"
                ? "Drop pipeline to add to context"
                : isDragging && dragSource === "file"
                  ? "Drop file to upload"
                  : "Drop files, data sources, assets, or pipelines here"}
        </span>
        <Layers className="h-4 w-4 opacity-40" />
        <Settings className="h-4 w-4 opacity-40" />
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,.txt,.md,.xlsx,.xls"
        className="hidden"
        onChange={handleUpload}
      />
    </div>
  );
}